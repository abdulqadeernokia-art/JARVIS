// The universe: spiral galaxy (GPU-animated points), deep starfield, volumetric-looking nebulae and drifting dust.
// All motion runs in vertex shaders, so the CPU only updates one uniform per layer per frame.
import { useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { NOISE } from "./noise";

function rand(seed: number) {
  return () => ((seed = (seed * 16807) % 2147483647) - 1) / 2147483646;
}

const pointVert = /* glsl */ `
uniform float uTime; uniform float uPixel;
attribute float aSize; attribute float aSpeed; attribute vec3 aColor;
varying vec3 vColor; varying float vTwinkle;
void main(){
  vec3 p = position;
  float r = length(p.xz);
  float ang = uTime * aSpeed / (0.6 + r * 0.08);           // differential rotation: inner stars orbit faster
  float c = cos(ang), s = sin(ang);
  p.xz = mat2(c, -s, s, c) * p.xz;
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  gl_Position = projectionMatrix * mv;
  vTwinkle = 0.75 + 0.25 * sin(uTime * 2.0 + position.x * 13.0 + position.z * 7.0);
  gl_PointSize = aSize * uPixel * (60.0 / -mv.z);
  vColor = aColor;
}`;
const pointFrag = /* glsl */ `
varying vec3 vColor; varying float vTwinkle;
void main(){
  float d = length(gl_PointCoord - 0.5);
  float a = smoothstep(0.5, 0.0, d);
  a = a * a;
  gl_FragColor = vec4(vColor * vTwinkle, a);
}`;

function makePoints(count: number, gen: (i: number, r: () => number) => [number, number, number, number, number, THREE.Color]) {
  const r = rand(count + 7);
  const pos = new Float32Array(count * 3), col = new Float32Array(count * 3);
  const size = new Float32Array(count), speed = new Float32Array(count);
  for (let i = 0; i < count; i++) {
    const [x, y, z, s, sp, c] = gen(i, r);
    pos.set([x, y, z], i * 3);
    col.set([c.r, c.g, c.b], i * 3);
    size[i] = s;
    speed[i] = sp;
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  g.setAttribute("aColor", new THREE.BufferAttribute(col, 3));
  g.setAttribute("aSize", new THREE.BufferAttribute(size, 1));
  g.setAttribute("aSpeed", new THREE.BufferAttribute(speed, 1));
  return g;
}

function PointLayer({ geometry, speed = 1, position, rotation }: { geometry: THREE.BufferGeometry; speed?: number; position?: [number, number, number]; rotation?: [number, number, number] }) {
  const mat = useMemo(
    () => new THREE.ShaderMaterial({
      uniforms: { uTime: { value: 0 }, uPixel: { value: Math.min(window.devicePixelRatio, 2) } },
      vertexShader: pointVert, fragmentShader: pointFrag,
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    }), []);
  useFrame((_, dt) => { mat.uniforms.uTime.value += dt * speed; });
  return <points geometry={geometry} material={mat} position={position} rotation={rotation} frustumCulled={false} />;
}

/** The main spiral galaxy, seen at a tilt beneath and behind the AI core. */
function SpiralGalaxy({ count }: { count: number }) {
  const geo = useMemo(() => {
    const inner = new THREE.Color("#fff3dc"), mid = new THREE.Color("#8fd6ff"), outer = new THREE.Color("#6a4bff");
    const arms = 4;
    return makePoints(count, (i, r) => {
      const radius = Math.pow(r(), 1.6) * 60 + 1.5;
      const arm = (i % arms) / arms * Math.PI * 2;
      const spin = radius * 0.11;
      const spread = (0.35 + radius * 0.018) * 6;
      const rx = Math.pow(r(), 3) * (r() < 0.5 ? 1 : -1) * spread;
      const ry = Math.pow(r(), 3) * (r() < 0.5 ? 1 : -1) * spread * 0.18 * (1.0 - radius / 80);
      const rz = Math.pow(r(), 3) * (r() < 0.5 ? 1 : -1) * spread;
      const x = Math.cos(arm + spin) * radius + rx, z = Math.sin(arm + spin) * radius + rz;
      const t = radius / 60;
      const c = t < 0.2 ? inner.clone().lerp(mid, t / 0.2) : mid.clone().lerp(outer, Math.min(1, (t - 0.2) / 0.8));
      c.multiplyScalar(0.55 + r() * 0.6);
      return [x, ry, z, 0.6 + r() * 1.4 + (radius < 6 ? 1.5 : 0), 0.02 + r() * 0.01, c];
    });
  }, [count]);
  return <PointLayer geometry={geo} position={[0, -9, -42]} rotation={[0.42, 0, 0.12]} />;
}

/** Deep background stars in a shell, plus a few distant galaxies. */
function StarField({ count }: { count: number }) {
  const geo = useMemo(() => {
    const palette = ["#ffffff", "#cfe4ff", "#a8c8ff", "#ffe8c8", "#d9ccff"].map((c) => new THREE.Color(c));
    return makePoints(count, (_, r) => {
      const u = r() * 2 - 1, th = r() * Math.PI * 2, rad = 160 + r() * 200;
      const s = Math.sqrt(1 - u * u);
      const c = palette[Math.floor(r() * palette.length)].clone().multiplyScalar(0.4 + r() * 0.8);
      return [s * Math.cos(th) * rad, u * rad, s * Math.sin(th) * rad, 1.2 + Math.pow(r(), 6) * 6, 0.0015, c];
    });
  }, [count]);
  return <PointLayer geometry={geo} />;
}

function DistantGalaxy({ position, rotation, tint, scale }: { position: [number, number, number]; rotation: [number, number, number]; tint: string; scale: number }) {
  const geo = useMemo(() => {
    const base = new THREE.Color(tint);
    return makePoints(3500, (i, r) => {
      const radius = Math.pow(r(), 1.8) * 10;
      const arm = (i % 2) * Math.PI;
      const a = arm + radius * 0.6 + (r() - 0.5) * 0.9;
      const c = base.clone().lerp(new THREE.Color("#fff6e0"), Math.max(0, 1 - radius / 3)).multiplyScalar(0.5 + r() * 0.5);
      return [Math.cos(a) * radius, (r() - 0.5) * 0.4, Math.sin(a) * radius, 0.8 + r(), 0.05, c];
    });
  }, [tint]);
  return <group scale={scale}><PointLayer geometry={geo} position={position} rotation={rotation} speed={0.6} /></group>;
}

const nebulaFrag = /* glsl */ `
uniform float uTime; uniform vec3 uA; uniform vec3 uB; uniform float uSeed; uniform float uOpacity;
varying vec2 vUv;
${NOISE}
void main(){
  vec2 p = vUv - 0.5;
  float d = length(p);
  vec3 q = vec3(p * 2.6, uSeed + uTime * 0.012);
  float n = fbm(q + fbm(q * 1.7 + uTime * 0.01) * 0.8);
  float density = smoothstep(0.0, 0.7, n + 0.25) * smoothstep(0.5, 0.05, d);
  float filaments = pow(smoothstep(0.2, 0.75, fbm(q * 3.0 + 4.0)), 2.0);
  vec3 col = mix(uA, uB, clamp(n * 0.9 + 0.5, 0.0, 1.0)) * (density + filaments * density * 0.8);
  gl_FragColor = vec4(col, density * uOpacity);
}`;
const planeVert = /* glsl */ `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;

function Nebula({ position, scale, a, b, seed, opacity = 0.55 }: { position: [number, number, number]; scale: number; a: string; b: string; seed: number; opacity?: number }) {
  const ref = useRef<THREE.Mesh>(null!);
  const mat = useMemo(
    () => new THREE.ShaderMaterial({
      uniforms: { uTime: { value: 0 }, uA: { value: new THREE.Color(a) }, uB: { value: new THREE.Color(b) }, uSeed: { value: seed }, uOpacity: { value: opacity } },
      vertexShader: planeVert, fragmentShader: nebulaFrag, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    }), [a, b, seed, opacity]);
  useFrame(({ camera }, dt) => {
    mat.uniforms.uTime.value += dt;
    ref.current.quaternion.copy(camera.quaternion); // billboards always face the camera
  });
  return <mesh ref={ref} position={position} scale={scale} material={mat}><planeGeometry args={[1, 1]} /></mesh>;
}

/** Slow foreground dust near the camera: gives parallax depth while orbiting. */
function Dust({ count }: { count: number }) {
  const geo = useMemo(() => makePoints(count, (_, r) => {
    const c = new THREE.Color("#9fdcff").multiplyScalar(0.25 + r() * 0.35);
    return [(r() - 0.5) * 70, (r() - 0.5) * 30, (r() - 0.5) * 70, 0.25 + r() * 0.5, 0.01 + r() * 0.03, c];
  }), [count]);
  return <PointLayer geometry={geo} />;
}

export function Universe({ quality }: { quality: "high" | "low" }) {
  const k = quality === "high" ? 1 : 0.25;
  return (
    <group>
      <StarField count={Math.round(9000 * k)} />
      <SpiralGalaxy count={Math.round(70000 * k)} />
      <DistantGalaxy position={[-140, 60, -220]} rotation={[1.1, 0.3, 0.4]} tint="#ffb98a" scale={1} />
      <DistantGalaxy position={[170, -40, -180]} rotation={[0.4, 0.2, -0.8]} tint="#8ab8ff" scale={1} />
      <DistantGalaxy position={[60, 110, 200]} rotation={[-0.6, 0.1, 0.2]} tint="#c9a6ff" scale={1} />
      <Nebula position={[-55, 18, -90]} scale={110} a="#1b2a8a" b="#6a2fb0" seed={1.3} />
      <Nebula position={[65, -12, -100]} scale={95} a="#0b5a8a" b="#2ad0ff" seed={7.1} opacity={0.4} />
      <Nebula position={[10, 30, -140]} scale={140} a="#3a1466" b="#1d4fd0" seed={3.7} opacity={0.45} />
      {quality === "high" && <Nebula position={[-80, -25, 60]} scale={120} a="#102a5a" b="#7a3fd0" seed={11.2} opacity={0.35} />}
      <Dust count={Math.round(1500 * k)} />
    </group>
  );
}
