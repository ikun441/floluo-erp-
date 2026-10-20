"use client";

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

export default function LoginScene({
  paused,
  reduced,
  busy,
}: {
  paused: boolean;
  reduced: boolean;
  busy: boolean;
}) {
  const host = useRef<HTMLDivElement>(null);
  const state = useRef({ paused, reduced, busy, dirty: true });
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    state.current = { paused, reduced, busy, dirty: true };
  }, [paused, reduced, busy]);
  useEffect(() => {
    const element = host.current;
    if (!element) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({
        alpha: true,
        antialias: true,
        powerPreference: "low-power",
      });
    } catch {
      setFailed(true);
      return;
    }
    renderer.setPixelRatio(
      Math.min(window.devicePixelRatio, window.innerWidth < 900 ? 1 : 1.5),
    );
    renderer.setClearColor(0x000000, 0);
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.22;
    element.appendChild(renderer.domElement);
    element.dataset.webgl = "ready";
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 40);
    camera.position.set(0, 0, 7.7);
    const environment = new RoomEnvironment();
    const generator = new THREE.PMREMGenerator(renderer);
    const env = generator.fromScene(environment, 0.04);
    scene.environment = env.texture;
    environment.dispose();
    generator.dispose();
    const world = new THREE.Group();
    world.position.y = 0.1;
    scene.add(world);
    const glass = new THREE.MeshPhysicalMaterial({
      color: 0xc3a9f5,
      metalness: 0.17,
      roughness: 0.075,
      transmission: 0.78,
      thickness: 1.1,
      ior: 1.43,
      clearcoat: 1,
      clearcoatRoughness: 0.04,
      iridescence: 0.65,
      iridescenceIOR: 1.3,
      iridescenceThicknessRange: [120, 430],
      attenuationColor: new THREE.Color(0x8a4bd6),
      attenuationDistance: 1.6,
      envMapIntensity: 2.25,
    });
    const narrow = window.innerWidth < 900;
    world.scale.setScalar(narrow ? 0.82 : 1);
    const sculpture = new THREE.Mesh(
      new THREE.TorusKnotGeometry(
        1.02,
        0.31,
        narrow ? 144 : 216,
        narrow ? 20 : 32,
        2,
        3,
      ),
      glass,
    );
    sculpture.rotation.set(0.35, 0.2, -0.27);
    world.add(sculpture);
    const core = new THREE.Mesh(
      new THREE.IcosahedronGeometry(0.36, 3),
      new THREE.MeshPhysicalMaterial({
        color: 0x9868e4,
        metalness: 0.8,
        roughness: 0.14,
        envMapIntensity: 2,
        clearcoat: 1,
      }),
    );
    world.add(core);
    const ringMaterial = new THREE.MeshBasicMaterial({
      color: 0xb6a2df,
      transparent: true,
      opacity: 0.24,
    });
    const rings = [1.85, 2.16].map((radius, i) => {
      const ring = new THREE.Mesh(
        new THREE.TorusGeometry(radius, 0.004, 6, 160),
        ringMaterial,
      );
      ring.rotation.set(1.14 + i * 0.4, 0.3 - i * 0.65, 0.15);
      world.add(ring);
      return ring;
    });
    const satellites = new THREE.Group();
    const satelliteMaterial = new THREE.MeshPhysicalMaterial({
      color: 0xe2caff,
      metalness: 0.62,
      roughness: 0.2,
      envMapIntensity: 2,
      clearcoat: 1,
    });
    const satelliteGeometry = new THREE.IcosahedronGeometry(0.075, 1);
    for (let i = 0; i < 3; i++) {
      const satellite = new THREE.Mesh(satelliteGeometry, satelliteMaterial);
      const angle = (i * Math.PI * 2) / 3;
      satellite.position.set(
        Math.cos(angle) * 1.9,
        Math.sin(angle) * 1.6,
        Math.sin(angle) * 0.7,
      );
      satellites.add(satellite);
    }
    world.add(satellites);
    let seed = 34;
    const random = () => {
      seed = (seed * 1664525 + 1013904223) >>> 0;
      return seed / 4294967296;
    };
    const positions = new Float32Array((narrow ? 44 : 86) * 3);
    for (let i = 0; i < positions.length; i += 3) {
      positions[i] = (random() - 0.5) * 9;
      positions[i + 1] = (random() - 0.5) * 7;
      positions[i + 2] = (random() - 0.5) * 5 - 1;
    }
    const dustGeometry = new THREE.BufferGeometry();
    dustGeometry.setAttribute(
      "position",
      new THREE.BufferAttribute(positions, 3),
    );
    const dust = new THREE.Points(
      dustGeometry,
      new THREE.PointsMaterial({
        color: 0xd1bdf2,
        size: 0.018,
        transparent: true,
        opacity: 0.6,
        sizeAttenuation: true,
        depthWrite: false,
      }),
    );
    scene.add(dust);
    const key = new THREE.DirectionalLight(0xe6d4ff, 4);
    key.position.set(-3, 4, 4);
    scene.add(key);
    const edge = new THREE.DirectionalLight(0x7856ff, 5);
    edge.position.set(4, -1, 2);
    scene.add(edge);
    const warm = new THREE.PointLight(0xee9fbf, 55, 10);
    warm.position.set(-2, -1, 2);
    scene.add(warm);
    scene.add(new THREE.AmbientLight(0xb5a5de, 1.1));
    const pointer = { x: 0, y: 0 };
    const resize = () => {
      const rect = element.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      renderer.setSize(rect.width, rect.height, false);
      camera.aspect = rect.width / rect.height;
      camera.updateProjectionMatrix();
      state.current.dirty = true;
    };
    const observer = new ResizeObserver(resize);
    observer.observe(element);
    resize();
    const move = (event: PointerEvent) => {
      if (state.current.reduced || state.current.paused) return;
      const rect = element.getBoundingClientRect();
      pointer.x = THREE.MathUtils.clamp(
        (event.clientX - rect.left) / rect.width - 0.5,
        -0.5,
        0.5,
      );
      pointer.y = THREE.MathUtils.clamp(
        (event.clientY - rect.top) / rect.height - 0.5,
        -0.5,
        0.5,
      );
    };
    window.addEventListener("pointermove", move, { passive: true });
    let elapsed = 0,
      lastTime = 0,
      lastRender = 0;
    renderer.setAnimationLoop((time) => {
      const delta = Math.min((time - lastTime) / 1000, 0.05);
      lastTime = time;
      if (document.hidden) return;
      const still = state.current.paused || state.current.reduced;
      if (still && !state.current.dirty) return;
      if (time - lastRender < 1000 / 30 && !state.current.dirty) return;
      lastRender = time;
      if (!still) elapsed += delta * (state.current.busy ? 1.8 : 1);
      sculpture.rotation.y = 0.2 + elapsed * 0.11;
      sculpture.rotation.x = 0.35 + Math.sin(elapsed * 0.18) * 0.12;
      sculpture.rotation.z = -0.27 + Math.sin(elapsed * 0.12) * 0.1;
      world.position.y = 0.1 + Math.sin(elapsed * 0.65) * 0.07;
      world.rotation.y = THREE.MathUtils.lerp(
        world.rotation.y,
        pointer.x * 0.24,
        0.055,
      );
      world.rotation.x = THREE.MathUtils.lerp(
        world.rotation.x,
        pointer.y * 0.14,
        0.055,
      );
      satellites.rotation.z = elapsed * 0.08;
      rings[1].rotation.z = elapsed * 0.035;
      core.rotation.y = elapsed * 0.2;
      dust.rotation.z = elapsed * 0.008;
      renderer.render(scene, camera);
      state.current.dirty = false;
    });
    const lost = (event: Event) => {
      event.preventDefault();
      renderer.setAnimationLoop(null);
      setFailed(true);
      element.dataset.webgl = "fallback";
    };
    renderer.domElement.addEventListener("webglcontextlost", lost);
    return () => {
      observer.disconnect();
      window.removeEventListener("pointermove", move);
      renderer.setAnimationLoop(null);
      renderer.domElement.removeEventListener("webglcontextlost", lost);
      const geometries = new Set<THREE.BufferGeometry>();
      const materials = new Set<THREE.Material>();
      scene.traverse((object) => {
        if (object instanceof THREE.Mesh || object instanceof THREE.Points) {
          geometries.add(object.geometry);
          for (const material of Array.isArray(object.material)
            ? object.material
            : [object.material])
            materials.add(material);
        }
      });
      geometries.forEach((geometry) => geometry.dispose());
      materials.forEach((material) => material.dispose());
      env.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
      renderer.domElement.remove();
    };
  }, []);
  return (
    <div
      className={"sculpture-host" + (failed ? " sculpture-failed" : "")}
      ref={host}
      aria-hidden="true"
    >
      <div className="sculpture-fallback">
        <i />
        <i />
        <i />
      </div>
    </div>
  );
}
