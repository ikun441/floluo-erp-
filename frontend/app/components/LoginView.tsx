"use client";

import dynamic from "next/dynamic";
import { useRef, useState, type FormEvent, type PointerEvent } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import {
  ArrowRight,
  Check,
  ChevronRight,
  Database,
  Eye,
  EyeOff,
  LoaderCircle,
  LockKeyhole,
  Pause,
  Play,
  ShieldCheck,
  Sparkles,
  UserRound,
} from "lucide-react";

const Scene = dynamic(() => import("./LoginScene"), {
  ssr: false,
  loading: () => <div className="sculpture-loading" aria-hidden="true" />,
});
type Props = {
  done: () => void;
  authenticate: (username: string, password: string) => Promise<unknown>;
};

export default function LoginView({ done, authenticate }: Props) {
  const reduced = !!useReducedMotion();
  const [paused, setPaused] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [phase, setPhase] = useState<"idle" | "busy" | "success">("idle");
  const button = useRef<HTMLButtonElement>(null);
  const enter = {
    initial: { opacity: 0, y: reduced ? 0 : 20 },
    animate: { opacity: 1, y: 0 },
  };
  const transition = (delay: number) => ({
    duration: reduced ? 0.01 : 0.7,
    delay: reduced ? 0 : delay,
    ease: [0.16, 1, 0.3, 1] as [number, number, number, number],
  });
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (phase !== "idle") return;
    const form = new FormData(event.currentTarget);
    setError("");
    setPhase("busy");
    try {
      await authenticate(
        String(form.get("username")),
        String(form.get("password")),
      );
      setPhase("success");
      if (!reduced) await new Promise((resolve) => setTimeout(resolve, 450));
      done();
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败，请稍后重试");
      setPhase("idle");
    }
  }
  function buttonGlow(event: PointerEvent<HTMLButtonElement>) {
    if (reduced) return;
    const rect = event.currentTarget.getBoundingClientRect();
    event.currentTarget.style.setProperty(
      "--glow-x",
      String(event.clientX - rect.left) + "px",
    );
    event.currentTarget.style.setProperty(
      "--glow-y",
      String(event.clientY - rect.top) + "px",
    );
  }
  return (
    <main className={"login-experience" + (paused ? " motion-paused" : "")}>
      <section className="login-stage" aria-label="弗洛洛品牌空间">
        <div className="stage-aura" aria-hidden="true" />
        <div className="stage-grid" aria-hidden="true" />
        <motion.header
          className="stage-header"
          {...enter}
          transition={transition(0.05)}
        >
          <a href="/" className="stage-brand" aria-label="弗洛洛 ERP 首页">
            <span className="stage-brand-icon logo-mark">
              <img
                className="product-logo"
                src="/brand/floluo-logo.png"
                alt="弗洛洛 ERP Logo"
                width={43}
                height={43}
                decoding="async"
              />
            </span>
            <span>
              弗洛洛<span className="stage-brand-erp">ERP</span>
              <small>FLOLUO WORKSPACE</small>
            </span>
          </a>
          <span className="stage-private">
            <span />
            PRIVATE BY DESIGN
          </span>
        </motion.header>
        <div className="login-scene-wrap">
          <Scene paused={paused} reduced={reduced} busy={phase !== "idle"} />
        </div>
        <div
          className="scene-annotation scene-annotation-top"
          aria-hidden="true"
        >
          <span className="annotation-line" />
          <span>01 — CONNECTED, BY NATURE</span>
        </div>
        <motion.div
          className="floating-feature feature-data"
          {...enter}
          transition={transition(0.7)}
          aria-hidden="true"
        >
          <span className="feature-icon">
            <Database size={18} />
          </span>
          <div>
            <small>CONNECTED BUSINESS</small>
            <strong>让数据，有序流动</strong>
          </div>
          <span className="feature-spark">✦</span>
        </motion.div>
        <motion.div
          className="floating-feature feature-permission"
          {...enter}
          transition={transition(0.9)}
          aria-hidden="true"
        >
          <span className="feature-icon">
            <ShieldCheck size={18} />
          </span>
          <div>
            <small>PRECISE BY DEFAULT</small>
            <strong>每一份权限，都有边界</strong>
          </div>
        </motion.div>
        <motion.div
          className="login-story"
          {...enter}
          transition={transition(0.25)}
        >
          <span className="story-kicker">
            <span />
            EVERYTHING, IN A BETTER FLOW.
          </span>
          <h2>
            将繁复，
            <br />
            <span>归于从容。</span>
            <span className="story-star" aria-hidden="true">
              ✦
            </span>
          </h2>
          <p>
            连接人与业务，让每一份协作自然发生。
            <br />
            一个工作空间，让企业运转得更好。
          </p>
        </motion.div>
        <motion.footer
          className="stage-footer"
          {...enter}
          transition={transition(0.55)}
        >
          <span>
            人 · 数据 · 业务 <span className="footer-line" /> 自然相连
          </span>
          <button
            type="button"
            className="motion-toggle"
            onClick={() => setPaused(!paused)}
            aria-pressed={paused}
            aria-label={paused ? "播放背景动画" : "暂停背景动画"}
          >
            {paused ? <Play size={12} /> : <Pause size={12} />}
            <span>{paused ? "播放动效" : "暂停动效"}</span>
          </button>
        </motion.footer>
      </section>
      <aside className="login-form-side">
        <motion.div
          className="login-edition"
          {...enter}
          transition={transition(0.1)}
        >
          <span>
            <Sparkles size={13} />
            企业工作空间
          </span>
          <span>
            V 1.0.5 <i>BETA</i>
          </span>
        </motion.div>
        <motion.section
          className="login-form-content"
          {...enter}
          transition={transition(0.25)}
          aria-labelledby="login-title"
        >
          <div className="login-welcome-icon logo-mark">
            <img
              className="product-logo"
              src="/brand/floluo-logo.png"
              alt="弗洛洛角色标志"
              width={76}
              height={76}
              decoding="async"
            />
          </div>
          <span className="form-eyebrow">WELCOME TO YOUR WORKSPACE</span>
          <h1 id="login-title">
            欢迎回来<span>。</span>
          </h1>
          <p className="login-subtitle">新的一天，从有序的工作开始。</p>
          <form onSubmit={submit} className="premium-login-form">
            <label className="premium-field">
              <span>
                工作账号<small>ACCOUNT</small>
              </span>
              <div className="premium-input">
                <UserRound size={17} />
                <input
                  name="username"
                  aria-label="工作账号"
                  placeholder="输入你的工作账号"
                  autoComplete="username"
                  required
                  maxLength={80}
                  disabled={phase !== "idle"}
                />
                <span className="input-focus-dot" />
              </div>
            </label>
            <label className="premium-field">
              <span>
                登录密码<small>PASSWORD</small>
              </span>
              <div className="premium-input">
                <LockKeyhole size={17} />
                <input
                  name="password"
                  aria-label="登录密码"
                  type={showPassword ? "text" : "password"}
                  placeholder="输入你的登录密码"
                  autoComplete="current-password"
                  required
                  maxLength={256}
                  disabled={phase !== "idle"}
                />
                <button
                  type="button"
                  className="password-toggle"
                  aria-label={showPassword ? "隐藏密码" : "显示密码"}
                  aria-pressed={showPassword}
                  onClick={() => setShowPassword(!showPassword)}
                >
                  {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
                </button>
              </div>
            </label>
            <div className="login-security-note">
              <ShieldCheck size={13} />
              <span>仅限已授权的企业成员访问</span>
              <span className="note-line" />
            </div>
            <AnimatePresence initial={false}>
              {error ? (
                <motion.div
                  key="login-error"
                  role="alert"
                  className="premium-error"
                  initial={{ opacity: 0, x: reduced ? 0 : -6 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, height: 0 }}
                >
                  {error === "invalid_credentials"
                    ? "账号或密码不正确，请重新输入。"
                    : error === "login_temporarily_unavailable"
                      ? "尝试次数过多，请稍后再试。"
                      : error}
                </motion.div>
              ) : null}
            </AnimatePresence>
            <motion.button
              ref={button}
              type="submit"
              className={"premium-submit phase-" + phase}
              onPointerMove={buttonGlow}
              disabled={phase !== "idle"}
              whileHover={reduced ? undefined : { y: -2 }}
              whileTap={reduced ? undefined : { scale: 0.985 }}
            >
              <span className="button-sheen" />
              <span>
                {phase === "busy"
                  ? "正在验证身份"
                  : phase === "success"
                    ? "身份已验证"
                    : "进入工作空间"}
              </span>
              <span className="submit-icon">
                {phase === "busy" ? (
                  <LoaderCircle size={18} className="login-spinner" />
                ) : phase === "success" ? (
                  <Check size={19} />
                ) : (
                  <ArrowRight size={18} />
                )}
              </span>
            </motion.button>
          </form>
          <div className="login-admin-help">
            <span>首次访问或忘记密码？</span>
            <details>
              <summary>
                联系系统管理员
                <ChevronRight size={12} />
              </summary>
              <p>
                请联系企业内部管理员。首次部署需在服务器初始化账号；已有账号可由具备权限的管理员重置密码。
              </p>
            </details>
          </div>
        </motion.section>
        <motion.footer
          className="form-side-footer"
          {...enter}
          transition={transition(0.55)}
        >
          <div className="footer-lock">
            <LockKeyhole size={12} />
            <span>你的企业 · 你的数据</span>
          </div>
          <span>用心连接，每一份协作。</span>
        </motion.footer>
      </aside>
    </main>
  );
}
