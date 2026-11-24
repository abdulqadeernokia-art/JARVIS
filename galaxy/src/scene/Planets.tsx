// Interactive planets. Each has a procedural surface (per-type shader), an atmosphere, an optional ring,
// a hover glow and a holographic label. Clicking starts the camera flight (CameraRig).
import { Html } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { PLANETS, type PlanetDef } from "../lib/planets";
import { useJarvis } from "../lib/store";
import { NOISE } from "./noise";

const SURFACE: Record<PlanetDef["surface"], string> = {
  gas: `float n = fbm(vec3(p.x*1.2, p.y*7.0 + fbm(p*2.0 + uTime*0.03)*1.5, p.z*1.2)); vec3 c = mix(uA, uB, n*0.5+0.5);`,
  rocky: `float n = fbm(p*2.5); float cr = smoothstep(0.55,0.6,abs(snoise(p*6.0))); vec3 c = mix(uA, uB, n*0.6+0.5) * (1.0 - cr*0.35);`,
  ocean: `float n = fbm(p*1.8 + 3.0); float land = smoothstep(0.05, 0.12, n); float cloud = smoothstep(0.2,0.6,fbm(p*3.0 + vec3(uTime*0.02,0.0,0.0)));
          vec3 c = mix(uA, uB, land) ; c = mix(c, vec3(1.0), cloud*0.55);`,
  ice: `float n = fbm(p*3.0); float cracks = 1.0 - smoothstep(0.0,0.04,abs(snoise(p*5.0))); vec3 c = mix(uA, uB, n*0.4+0.4) + uB*cracks*0.6;`,
  lava: `float n = fbm(p*2.2 + uTime*0.02); float glow = pow(smoothstep(0.1,0.0,abs(n)),3.0); vec3 c = mix(uA*0.4, uA, n*0.5+0.5) + uB*glow*2.0;`,
  tech: `float n = fbm(p*2.0); vec2 g = abs(fract(vec2(atan(p.z,p.x)*6.0, p.y*8.0))-0.5); float grid = smoothstep(0.47,0.5,max(g.x,g.y));
         float pulse = 0.5+0.5*sin(uTime*2.0 + p.y*10.0); vec3 c = mix(uA, uA*1.6, n*0.5+0.5) + uB*grid*(0.4+pulse*0.6);`,
};

function makeSurface(p: PlanetDef) {
  return new THREE.ShaderMaterial({
    uniforms: {
      uTime: { value: 0 }, uA: { value: new THREE.Color(p.colors[0]) }, uB: { value: new THREE.Color(p.colors[1]) },
      uHover: { value: 0 }, uSun: { value: new THREE.Vector3(0, 0, 0) },
    },
    vertexShader: /* glsl */ `
      varying vec3 vP; varying vec3 vN; varying vec3 vW; varying vec3 vView;
      void main(){ vP = position; vN = normalize(mat3(modelMatrix) * normal); vec4 w = modelMatrix * vec4(position,1.0); vW = w.xyz;
        vView = normalize(cameraPosition - w.xyz); gl_Position = projectionMatrix * viewMatrix * w; }`,
    fragmentShader: /* glsl */ `
      uniform float uTime; uniform vec3 uA; uniform vec3 uB; uniform float uHover; uniform vec3 uSun;
      varying vec3 vP; varying vec3 vN; varying vec3 vW; varying vec3 vView;
      ${NOISE}
      void main(){
        vec3 p = normalize(vP);
        ${SURFACE[p.surface]}
        vec3 L = normalize(uSun - vW);                    // lit by the AI core at the centre of the system
        float diff = smoothstep(-0.25, 1.0, dot(vN, L));
        float rim = pow(1.0 - max(dot(vN, vView), 0.0), 3.0);
        vec3 col = c * (0.08 + diff * 1.05) + uB * rim * (0.25 + uHover * 0.9);
        gl_FragColor = vec4(col, 1.0);
      }`,
  });
}

function Atmosphere({ radius, color, hover }: { radius: number; color: string; hover: React.MutableRefObject<number> }) {
  const mat = useMemo(() => new THREE.ShaderMaterial({
    uniforms: { uC: { value: new THREE.Color(color) }, uHover: { value: 0 } },
    vertexShader: /* glsl */ `varying vec3 vN; varying vec3 vV; void main(){ vec4 w = modelMatrix*vec4(position,1.0);
      vN = normalize(mat3(modelMatrix)*normal); vV = normalize(cameraPosition - w.xyz); gl_Position = projectionMatrix*viewMatrix*w; }`,
    fragmentShader: /* glsl */ `uniform vec3 uC; uniform float uHover; varying vec3 vN; varying vec3 vV;
      void main(){ float f = pow(1.0 - abs(dot(vN, vV)), 2.5); gl_FragColor = vec4(uC, f * (0.45 + uHover * 0.35)); }`,
    transparent: true, depthWrite: false, side: THREE.BackSide, blending: THREE.AdditiveBlending,
  }), [color]);
  useFrame(() => { mat.uniforms.uHover.value = hover.current; });
  return <mesh material={mat} scale={radius * 1.18}><sphereGeometry args={[1, 48, 48]} /></mesh>;
}

function PlanetRing({ radius, color }: { radius: number; color: string }) {
  const mat = useMemo(() => new THREE.ShaderMaterial({
    uniforms: { uC: { value: new THREE.Color(color) } },
    vertexShader: /* glsl */ `varying vec3 vP; void main(){ vP = position; gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0); }`,
    fragmentShader: /* glsl */ `uniform vec3 uC; varying vec3 vP;
      void main(){ float r = length(vP.xy); float bands = 0.5 + 0.5*sin(r*60.0) * sin(r*17.0);
        float a = smoothstep(${(radius * 1.35).toFixed(2)}, ${(radius * 1.45).toFixed(2)}, r) * smoothstep(${(radius * 2.3).toFixed(2)}, ${(radius * 2.0).toFixed(2)}, r);
        gl_FragColor = vec4(uC, a * bands * 0.55); }`,
    transparent: true, depthWrite: false, side: THREE.DoubleSide,
  }), [radius, color]);
  return <mesh material={mat} rotation={[-Math.PI / 2.3, 0.2, 0]}><ringGeometry args={[radius * 1.3, radius * 2.35, 128]} /></mesh>;
}

function Planet({ def }: { def: PlanetDef }) {
  const mesh = useRef<THREE.Mesh>(null!);
  const group = useRef<THREE.Group>(null!);
  const hover = useRef(0);
  const mat = useMemo(() => makeSurface(def), [def]);
  const hovered = useJarvis((s) => s.hover === def.id);
  const focused = useJarvis((s) => s.focus === def.id);
  const seed = useMemo(() => def.position[0] * 0.37 + def.position[2] * 0.11, [def]);

  useFrame(({ clock }, dt) => {
    const t = clock.elapsedTime;
    mesh.current.rotation.y += dt * 0.08;
    // gentle float, so the planets never look pinned to the background
    group.current.position.set(def.position[0], def.position[1] + Math.sin(t * 0.3 + seed) * 0.25, def.position[2]);
    hover.current += ((hovered || focused ? 1 : 0) - hover.current) * Math.min(1, dt * 6);
    mat.uniforms.uTime.value = t;
    mat.uniforms.uHover.value = hover.current;
    group.current.scale.setScalar(1 + (hovered ? hover.current * 0.08 : 0));
  });

  const st = useJarvis.getState;
  return (
    <group ref={group} position={def.position}>
      <mesh ref={mesh} material={mat} scale={def.radius}
        onPointerOver={(e) => { e.stopPropagation(); st().setHover(def.id); document.body.style.cursor = "pointer"; }}
        onPointerOut={() => { if (st().hover === def.id) st().setHover(null); document.body.style.cursor = ""; }}
        onClick={(e) => { e.stopPropagation(); st().setFocus(def.id); }}>
        <sphereGeometry args={[1, 64, 64]} />
      </mesh>
      <Atmosphere radius={def.radius} color={def.colors[2]} hover={hover} />
      {def.ring && <PlanetRing radius={def.radius} color={def.colors[2]} />}
      <Html center position={[0, def.radius + 0.9, 0]} style={{ pointerEvents: "none" }} zIndexRange={[10, 0]}>
        <div className={`planet-label ${hovered ? "on" : ""}`}>
          <div className="name"><span className="key">{def.shortcut}</span>{def.name}</div>
          {hovered && (
            <div className="holo">
              <div className="desc">{def.description}</div>
              <div className="meta">CLICK TO TRAVEL · {def.links?.length ? `${def.links.length} DESTINATIONS` : "SYSTEM MODULE"}</div>
            </div>
          )}
        </div>
      </Html>
    </group>
  );
}

/** Faint orbit lines connecting each planet to the core: subtle holographic structure. */
function Orbits() {
  const geo = useMemo(() => {
    const g = new THREE.BufferGeometry();
    const pts: number[] = [];
    for (const p of PLANETS) {
      const r = Math.hypot(p.position[0], p.position[2]);
      const seg = 160;
      for (let i = 0; i < seg; i++) {
        const a0 = (i / seg) * Math.PI * 2, a1 = ((i + 1) / seg) * Math.PI * 2;
        pts.push(Math.cos(a0) * r, p.position[1] * 0.0, Math.sin(a0) * r, Math.cos(a1) * r, 0, Math.sin(a1) * r);
      }
    }
    g.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
    return g;
  }, []);
  return (
    <lineSegments geometry={geo} position={[0, -0.8, 0]}>
      <lineBasicMaterial color="#3fb8ff" transparent opacity={0.06} blending={THREE.AdditiveBlending} depthWrite={false} />
    </lineSegments>
  );
}

export function Planets() {
  return (
    <group>
      <Orbits />
      {PLANETS.map((p) => <Planet key={p.id} def={p} />)}
    </group>
  );
}
