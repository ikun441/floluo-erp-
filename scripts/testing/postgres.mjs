import EmbeddedPostgres from "embedded-postgres";
import { mkdtemp, mkdir, chmod } from "node:fs/promises";
import { spawn } from "node:child_process";
import { createServer } from "node:net";
import { randomBytes } from "node:crypto";
import path from "node:path";
const root = path.resolve(import.meta.dirname, "../..");
const runtime = path.join(root, ".test-runtime");
await mkdir(runtime, { recursive: true, mode: 0o700 });
const directory = await mkdtemp(path.join(runtime, "postgres-"));
await chmod(directory, 0o700);
const socket = createServer();
await new Promise((resolve) => socket.listen(0, "127.0.0.1", resolve));
const port = socket.address().port;
await new Promise((resolve) => socket.close(resolve));
const password = randomBytes(24).toString("hex");
const pg = new EmbeddedPostgres({
  databaseDir: path.join(directory, "data"),
  user: "erp_test",
  password,
  port,
  persistent: true,
  authMethod: "scram-sha-256",
  postgresFlags: ["-h", "127.0.0.1"],
  onLog: () => {},
  onError: () => {},
});
let exit = 1;
try {
  await pg.initialise();
  await pg.start();
  await pg.createDatabase("erp_test");
  console.log("Temporary PostgreSQL ready; credentials withheld.");
  const url =
    "postgresql+psycopg://erp_test:" +
    password +
    "@127.0.0.1:" +
    port +
    "/erp_test";
  exit = await new Promise((resolve, reject) => {
    const child = spawn(
      path.join(root, ".venv/bin/python"),
      ["-m", "pytest", "-q"],
      {
        cwd: root,
        stdio: "inherit",
        env: { ...process.env, TEST_POSTGRES_URL: url },
      },
    );
    child.on("error", reject);
    child.on("exit", (code) => resolve(code ?? 1));
  });
} catch {
  console.error("Temporary PostgreSQL verification failed");
  exit = 1;
} finally {
  await pg.stop();
}
process.exit(exit);
