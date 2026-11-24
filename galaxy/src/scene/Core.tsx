// The JARVIS AI core. Each state has its own colour, motion and ring behaviour. Its energy comes from the real
// microphone level (LISTENING) and the real speech envelope from TTS word timings (SPEAKING), both streamed
// from the Python core at 30 Hz.
import { useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { levels, send } from "../lib/bridge";
import { useJarvis, type CoreState } from "../lib/store";
import { NOISE } from "./noise";

const STATE_LOOK: Record<CoreState, { color: string; accent: string; spin: number; pulse: number }> = {
  idle: { color: "#3fb8ff", accent: "#bff3ff", spin: 0.15, pulse: 0.15 },
  listening: { color: "#4ff2ff", accent: "#e8ffff", spin: 0.35, pulse: 0.3 },
  thinking: { color: "#6c8cff", accent: "#d6c8ff", spin: 1.4, pulse: 0.5 },
  speaking: { color: "#55d6ff", accent: "#ffffff", spin: 0.5, pulse: 0.4 },
  executing: { color: "#38ffc8", accent: "#d6fff2", spin: 0.9, pulse: 0.45 },
  approval: { color: "#ffc44d", accent: "#fff1c8", spin: 0.3, pulse: 0.6 },
  error: { color: "#ff4d5e", accent: "#ffd0d4", spin: 0.1, pulse: 0.9 },
  privacy: { color: "#3a4a66", accent: "#7d8aa6", spin: 0.05, pulse: 0.05 },
};

const coreVert = /* glsl */ `
uniform float uTime; uniform float uEnergy;
varying vec3 vN; varying vec3 vView; varying float vNoise;
${NOISE}
void main(){
  float n = snoise(normal * 2.2 + uTime * 0.6);
  vNoise = n;
  vec3 p = position + normal * n * (0.05 + uEnergy * 0.22);
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  vN = normalize(normalMatrix * normal);
  vView = normalize(-mv.xyz);
  gl_Position = projectionMatrix * mv;
}`;
const coreFrag = /* glsl */ `
uniform vec3 uColor; uniform vec3 uAccent; uniform float uEnergy; uniform float uTime;
varying vec3 vN; varying vec3 vView; varying float vNoise;
void main(){
  float fres = pow(1.0 - max(dot(vN, vView), 0.0), 2.2);
  float core = pow(max(dot(vN, vView), 0.0), 3.0);
  vec3 col = uColor * (0.35 + fres * 1.6) + uAccent * core * (0.6 + uEnergy * 1.2);
  col += uAccent * smoothstep(0.35, 0.9, vNoise) * 0.35 * (0.4 + uEnergy);
  gl_FragColor = vec4(col, 0.92);
}`;

const glowFrag = /* glsl */ `
uniform vec3 uColor; uniform float uEnergy; varying vec2 vUv;
void main(){
  float d = length(vUv - 0.5) * 2.0;
  float g = pow(max(0.0, 1.0 - d), 2.6) * (0.55 + uEnergy * 0.9);
  gl_FragColor = vec4(uColor * g, g);
}`;
const planeVert = /* glsl */ `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;

/** Circular waveform: 128 radial samples displaced by the live audio energy. */
function Waveform({ energyRef, color }: { energyRef: React.MutableRefObject<number>; color: THREE.Color }) {
  const N = 160;
  const geo = useMemo(() => {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(new Float32Array((N + 1) * 3), 3));
    return g;
  }, []);
  const mat = useMemo(() => new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.85, blending: THREE.AdditiveBlending }), []);
  const line = useMemo(() => new THREE.Line(geo, mat), [geo, mat]);
  const history = useRef(new Float32Array(N));
  useFrame(({ clock }) => {
    const t = clock.elapsedTime;
    const h = history.current;
    h.copyWithin(1, 0); // scroll the energy history around the ring
    h[0] = energyRef.current;
    const pos = geo.attributes.position as THREE.BufferAttribute;
    for (let i = 0; i <= N; i++) {
      const k = i % N;
      const a = (k / N) * Math.PI * 2;
      const e = h[Math.min(k, N - 1 - k) * 2 % N] || 0;
      const r = 1.62 + e * 0.45 * (0.6 + 0.4 * Math.sin(a * 6 + t * 3)) + Math.sin(a * 3 + t) * 0.01;
      pos.setXYZ(i, Math.cos(a) * r, Math.sin(a) * r, 0);
    }
    pos.needsUpdate = true;
    mat.color.copy(color);
  });
  return <primitive object={line} />;
}

function Ring({ radius, width, speed, tilt, dashes, energyRef, color }: { radius: number; width: number; speed: number; tilt: [number, number, number]; dashes: number; energyRef: React.MutableRefObject<number>; color: THREE.Color }) {
  const ref = useRef<THREE.Mesh>(null!);
  const mat = useMemo(() => new THREE.ShaderMaterial({
    uniforms: { uColor: { value: color }, uTime: { value: 0 }, uDashes: { value: dashes }, uEnergy: { value: 0 } },
    vertexShader: planeVert,
    fragmentShader: /* glsl */ `
      uniform vec3 uColor; uniform float uTime; uniform float uDashes; uniform float uEnergy; varying vec2 vUv;
      void main(){
        float a = vUv.x;
        float dash = uDashes > 0.0 ? step(0.35, fract(a * uDashes)) : 1.0;
        float edge = smoothstep(0.0, 0.3, vUv.y) * smoothstep(1.0, 0.7, vUv.y);
        float sweep = pow(fract(a - uTime * 0.15), 8.0);
        float al = (0.25 + sweep * 0.9 + uEnergy * 0.4) * dash * edge;
        gl_FragColor = vec4(uColor * (1.0 + sweep), al);
      }`,
    transparent: true, depthWrite: false, side: THREE.DoubleSide, blending: THREE.AdditiveBlending,
  }), [dashes]);
  const geo = useMemo(() => {
    // ring with UVs running around the circumference (x) and across the band (y)
    const seg = 256, g = new THREE.BufferGeometry(), pos: number[] = [], uv: number[] = [], idx: number[] = [];
    for (let i = 0; i <= seg; i++) {
      const a = (i / seg) * Math.PI * 2;
      for (const [j, r] of [[0, radius - width / 2], [1, radius + width / 2]] as const) {
        pos.push(Math.cos(a) * r, Math.sin(a) * r, 0);
        uv.push(i / seg, j);
      }
      if (i < seg) idx.push(i * 2, i * 2 + 1, i * 2 + 2, i * 2 + 1, i * 2 + 3, i * 2 + 2);
    }
    g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2));
    g.setIndex(idx);
    return g;
  }, [radius, width]);
  useFrame((_, dt) => {
    const spin = (useJarvis.getState().state === "thinking" ? 3 : 1);
    ref.current.rotation.z += dt * speed * spin;
    mat.uniforms.uTime.value += dt * spin;
    mat.uniforms.uEnergy.value = energyRef.current;
  });
  return <group rotation={tilt}><mesh ref={ref} geometry={geo} material={mat} /></group>;
}

function Sparks({ energyRef, color }: { energyRef: React.MutableRefObject<number>; color: THREE.Color }) {
  const N = 600;
  const geo = useMemo(() => {
    const g = new THREE.BufferGeometry();
    const p = new Float32Array(N * 3), s = new Float32Array(N);
    for (let i = 0; i < N; i++) {
      const u = Math.random() * 2 - 1, th = Math.random() * Math.PI * 2, r = 1.2 + Math.random() * 1.6;
      const q = Math.sqrt(1 - u * u);
      p.set([q * Math.cos(th) * r, u * r, q * Math.sin(th) * r], i * 3);
      s[i] = Math.random();
    }
    g.setAttribute("position", new THREE.BufferAttribute(p, 3));
    g.setAttribute("aSeed", new THREE.BufferAttribute(s, 1));
    return g;
  }, []);
  const mat = useMemo(() => new THREE.ShaderMaterial({
    uniforms: { uTime: { value: 0 }, uEnergy: { value: 0 }, uColor: { value: color } },
    vertexShader: /* glsl */ `
      uniform float uTime; uniform float uEnergy; attribute float aSeed; varying float vA;
      void main(){
        float t = fract(aSeed + uTime * (0.05 + aSeed * 0.08));
        vec3 p = position * (0.85 + t * (0.6 + uEnergy * 0.8));
        vA = sin(t * 3.14159) * (0.35 + uEnergy);
        vec4 mv = modelViewMatrix * vec4(p, 1.0);
        gl_PointSize = (1.5 + aSeed * 2.5) * (30.0 / -mv.z);
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: /* glsl */ `uniform vec3 uColor; varying float vA;
      void main(){ float d = length(gl_PointCoord - 0.5); float a = smoothstep(0.5, 0.0, d) * vA; gl_FragColor = vec4(uColor, a); }`,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  }), []);
  useFrame((_, dt) => { mat.uniforms.uTime.value += dt; mat.uniforms.uEnergy.value = energyRef.current; });
  return <points geometry={geo} material={mat} />;
}

export function Core() {
  const group = useRef<THREE.Group>(null!);
  const facing = useRef<THREE.Group>(null!);
  const energy = useRef(0);
  const color = useMemo(() => new THREE.Color(STATE_LOOK.idle.color), []);
  const accent = useMemo(() => new THREE.Color(STATE_LOOK.idle.accent), []);
  const coreMat = useMemo(() => new THREE.ShaderMaterial({
    uniforms: { uTime: { value: 0 }, uEnergy: { value: 0 }, uColor: { value: color }, uAccent: { value: accent } },
    vertexShader: coreVert, fragmentShader: coreFrag, transparent: true,
  }), []);
  const glowMat = useMemo(() => new THREE.ShaderMaterial({
    uniforms: { uColor: { value: color }, uEnergy: { value: 0 } },
    vertexShader: planeVert, fragmentShader: glowFrag, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  }), []);
  const tmp = useMemo(() => new THREE.Color(), []);

  useFrame(({ clock, camera }, dt) => {
    const st = useJarvis.getState().state;
    const look = STATE_LOOK[st];
    const t = clock.elapsedTime;
    // Real audio drives energy; states add their own baseline motion.
    let target = look.pulse * (0.5 + 0.5 * Math.sin(t * (st === "error" ? 9 : 1.6)));
    if (st === "listening") target = 0.15 + levels.mic * 1.4;
    if (st === "speaking") target = 0.2 + levels.speech * 0.9;
    if (st === "thinking") target = 0.35 + 0.25 * Math.sin(t * 6) * Math.sin(t * 2.3);
    if (st === "idle" && levels.mic > 0.15) target += levels.mic * 0.4; // ambient voice shows even in standby
    energy.current += (Math.min(target, 1.4) - energy.current) * Math.min(1, dt * 10);
    color.lerp(tmp.set(look.color), Math.min(1, dt * 3));
    accent.lerp(tmp.set(look.accent), Math.min(1, dt * 3));
    coreMat.uniforms.uTime.value += dt * (0.6 + look.spin);
    coreMat.uniforms.uEnergy.value = energy.current;
    glowMat.uniforms.uEnergy.value = energy.current;
    group.current.rotation.y += dt * look.spin * 0.3;
    const s = 1 + energy.current * 0.08;
    group.current.scale.setScalar(s);
    facing.current.quaternion.copy(camera.quaternion);
  });

  return (
    <group>
      <group ref={group}>
        <mesh material={coreMat} onClick={(e) => { e.stopPropagation(); send("wake"); }}
          onPointerOver={() => (document.body.style.cursor = "pointer")} onPointerOut={() => (document.body.style.cursor = "")}>
          <icosahedronGeometry args={[1, 24]} />
        </mesh>
        <Sparks energyRef={energy} color={accent} />
      </group>
      <group ref={facing}>
        <mesh material={glowMat} scale={7}><planeGeometry args={[1, 1]} /></mesh>
        <Waveform energyRef={energy} color={accent} />
        <Ring radius={1.95} width={0.04} speed={0.3} tilt={[0, 0, 0]} dashes={0} energyRef={energy} color={color} />
        <Ring radius={2.25} width={0.09} speed={-0.18} tilt={[0, 0, 0]} dashes={72} energyRef={energy} color={color} />
        <Ring radius={2.7} width={0.025} speed={0.08} tilt={[0, 0, 0]} dashes={6} energyRef={energy} color={accent} />
      </group>
      <Ring radius={3.2} width={0.03} speed={0.12} tilt={[1.25, 0.2, 0]} dashes={24} energyRef={energy} color={color} />
      <Ring radius={3.6} width={0.02} speed={-0.07} tilt={[1.4, -0.35, 0.3]} dashes={0} energyRef={energy} color={color} />
      <pointLight color={color} intensity={30} distance={40} decay={1.6} />
    </group>
  );
}
