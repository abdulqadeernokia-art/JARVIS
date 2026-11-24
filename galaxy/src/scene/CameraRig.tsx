// Camera: free orbit (drag to rotate, wheel to zoom) around the core, plus cinematic flights to planets.
// Flights use an eased curve that arcs away from the core, so the camera never passes through it.
import { OrbitControls } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useRef } from "react";
import * as THREE from "three";
import type { OrbitControls as OC } from "three-stdlib";
import { planetById } from "../lib/planets";
import { useJarvis } from "../lib/store";

export const HOME = new THREE.Vector3(0, 4.5, 21);
const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

export function CameraRig() {
  const { camera } = useThree();
  const controls = useRef<OC>(null!);
  const flight = useRef<null | { from: THREE.Vector3; to: THREE.Vector3; mid: THREE.Vector3; lookFrom: THREE.Vector3; lookTo: THREE.Vector3; t: number; dur: number; arrive?: () => void }>(null);
  const intro = useRef(0);
  const focus = useJarvis((s) => s.focus);

  useEffect(() => {
    camera.position.set(0, 30, 70); // intro: start far out and drift in
  }, []);

  useEffect(() => {
    const c = controls.current;
    if (!c) return;
    const p = planetById(focus);
    if (!focus && intro.current < 1) return; // initial mount: let the intro play
    intro.current = 1; // any flight ends the intro
    const from = camera.position.clone();
    const lookFrom = c.target.clone();
    let to: THREE.Vector3, lookTo: THREE.Vector3;
    if (p) {
      const pp = new THREE.Vector3(...p.position);
      const dir = pp.clone().normalize();
      // park beside the planet, offset sideways so the panel (right side) has room
      const side = new THREE.Vector3().crossVectors(dir, new THREE.Vector3(0, 1, 0)).normalize();
      to = pp.clone().add(dir.clone().multiplyScalar(p.radius * 6.5)).add(side.multiplyScalar(p.radius * 3.2)).add(new THREE.Vector3(0, p.radius * 0.6, 0));
      lookTo = pp.clone().add(new THREE.Vector3().crossVectors(dir, new THREE.Vector3(0, 1, 0)).normalize().multiplyScalar(-p.radius * 2.6));
    } else {
      to = HOME.clone();
      lookTo = new THREE.Vector3(0, 0, 0);
    }
    const mid = from.clone().add(to).multiplyScalar(0.5);
    mid.add(mid.clone().normalize().multiplyScalar(Math.max(6, from.distanceTo(to) * 0.35))).add(new THREE.Vector3(0, 3, 0));
    flight.current = { from, to, mid, lookFrom, lookTo, t: 0, dur: p ? 2.4 : 2.0, arrive: () => p && useJarvis.getState().set({ panelOpen: true }) };
    c.enabled = false;
  }, [focus]);

  useFrame((_, dt) => {
    const c = controls.current;
    if (!c) return;
    if (intro.current < 1 && !flight.current) {
      intro.current = Math.min(1, intro.current + dt / 4.5);
      camera.position.lerpVectors(new THREE.Vector3(0, 30, 70), HOME, ease(intro.current));
      c.target.set(0, 0, 0);
    }
    const f = flight.current;
    if (f) {
      f.t = Math.min(1, f.t + dt / f.dur);
      const k = ease(f.t);
      // quadratic Bezier arc
      const a = f.from.clone().lerp(f.mid, k), b = f.mid.clone().lerp(f.to, k);
      camera.position.copy(a.lerp(b, k));
      c.target.lerpVectors(f.lookFrom, f.lookTo, k);
      if (f.t >= 1) {
        flight.current = null;
        c.enabled = true;
        f.arrive?.();
      }
    }
    c.update();
  });

  return (
    <OrbitControls ref={controls as any} enableDamping dampingFactor={0.06} rotateSpeed={0.45} zoomSpeed={0.6}
      minDistance={3} maxDistance={90} enablePan={false} autoRotate={!focus} autoRotateSpeed={0.12} />
  );
}
