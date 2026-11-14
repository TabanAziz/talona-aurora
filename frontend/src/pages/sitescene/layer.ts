import * as THREE from 'three';
import { labelTexture, tokenColor } from '../../components/plan3d/primitives';
import type { SiteLayerContext, SiteSceneOptions } from '../../components/site3d/siteScene';
import type { SiteActor } from './actors';

/** Schematic assignment transitions take eight seconds, once per changed source, not a work simulation. */
export const TRAVEL_MS = 8000;

export function actorLayer(read: () => SiteActor[]): NonNullable<SiteSceneOptions['layer']> {
  const started = new Map<string,number>();
  return (context: SiteLayerContext) => {
    const {group,centre,width,depth,top,units,host,reducedMotion} = context;
    const root = new THREE.Group();
    group.add(root);
    const font = getComputedStyle(document.body).fontFamily;
    function material(token: string) { return new THREE.MeshLambertMaterial({color:tokenColor(token)}); }
    function box(w:number,h:number,d:number,x:number,y:number,z:number,token='--text-muted') {
      const object = new THREE.Mesh(new THREE.BoxGeometry(w,h,d),material(token));
      object.position.set(x,y+h/2,z);
      return object;
    }
    function label(text:string,x:number,y:number,z:number,w:number,token='--text') {
      const object = new THREE.Mesh(new THREE.PlaneGeometry(w,w/4),new THREE.MeshBasicMaterial({
        map:labelTexture(text,tokenColor(token),font),transparent:true,depthWrite:false,
      }));
      object.rotation.x=-Math.PI/2;
      object.position.set(x,y,z);
      return object;
    }
    const laydown = new THREE.Vector3(centre.x-width/2+3,0.2,centre.z+depth/2-5);
    root.add(box(5,0.08,3,laydown.x,0,laydown.z,'--surface-2'));
    for(let i=0;i<3;i++) root.add(box(2.2,0.18,0.55,laydown.x,0.08+i*0.19,laydown.z,'--text-faint'));
    root.add(label('LAYDOWN · SCHEMATIC',laydown.x,0.8,laydown.z+1.6,4));
    const gate = new THREE.Vector3(centre.x,0.1,centre.z+depth/2-1.5);
    const items: {actor:SiteActor;object:THREE.Group;from:THREE.Vector3;end:THREE.Vector3;arm?:THREE.Group;heading?:number;start:number}[]=[];
    for(const actor of read()) {
      const object = new THREE.Group();
      root.add(object);
      const target = actor.unit ? units.get(actor.unit)?.clone() : undefined;
      const end = target?.clone() ?? gate.clone();
      end.x += actor.kind==='crew' ? -0.6 : actor.kind==='robot' ? 0.6 : 0;
      if(actor.kind==='drone') end.y+=2.5;
      const from = end.clone().add(new THREE.Vector3(-2,0,0));
      const color = actor.motion ? '--accent' : '--danger';
      let arm:THREE.Group|undefined;
      let heading:number|undefined;
      if(actor.kind==='truck') {
        end.copy(laydown).add(new THREE.Vector3(3,0,-0.5));
        if(!actor.motion) end.copy(gate);
        from.copy(gate);
        object.add(box(1.2,0.8,2.3,0,0.4,0,color));
        object.add(box(1.2,0.9,0.8,0,0.4,1.35,color));
        for(const x of [-0.7,0.7]) for(const z of [-0.7,0.7]) object.add(box(0.25,0.45,0.45,x,0.12,z));
      } else if(actor.kind==='crane') {
        const base=new THREE.Vector3(centre.x+width/2-2,0,centre.z+depth/2-3);
        const height=top+4;
        end.copy(base); from.copy(base);
        object.add(box(0.75,height,0.75,0,0,0,'--accent'));
        for(let y=1;y<height;y+=2) object.add(box(1,0.12,1,0,y,0));
        arm=new THREE.Group(); arm.position.y=height; object.add(arm);
        const distance=target?Math.hypot(target.x-base.x,target.z-base.z):width*0.45;
        heading=target?Math.atan2(target.x-base.x,target.z-base.z):0;
        arm.add(box(0.4,0.4,distance+3,0,0,distance/2-1.5,'--accent'));
        const drop=height-(target?.y??1);
        arm.add(box(0.04,drop,0.04,0,-drop,distance));
        arm.add(box(0.4,0.3,0.4,0,-drop,distance,color));
      } else if(actor.kind==='crew') {
        object.add(box(0.35,0.9,0.35,0,0,0,color));
        const head=new THREE.Mesh(new THREE.SphereGeometry(0.18,8,6),material('--text'));
        head.position.y=1.08; object.add(head);
      } else if(actor.kind==='robot') {
        object.add(box(0.65,0.4,0.7,0,0.12,0,color));
        object.add(box(0.08,0.7,0.08,0,0.52,0));
      } else {
        object.add(box(0.35,0.2,0.35,0,0,0,color));
        object.add(box(1.1,0.06,0.08,0,0.15,0));
        object.add(box(0.08,0.06,1.1,0,0.15,0));
        for(const x of [-0.5,0.5]) for(const z of [-0.5,0.5]) {
          const rotor=new THREE.Mesh(new THREE.CylinderGeometry(0.28,0.28,0.02,12),material('--text-muted'));
          rotor.position.set(x,0.18,z); object.add(rotor);
        }
      }
      object.add(label(actor.label,0,actor.kind==='crane'?top+5:1.5,1.1,3.8,color));
      if(!actor.motion) {
        const sign=new THREE.Mesh(new THREE.CircleGeometry(0.4,8),new THREE.MeshBasicMaterial({color:tokenColor('--danger'),side:THREE.DoubleSide}));
        sign.position.set(0.75,1,0); object.add(sign);
        object.add(label('STOP · '+actor.reason.slice(0,64),1.2,1.9,0.6,5.2,'--danger'));
      }
      if(!started.has(actor.signature)) started.set(actor.signature,performance.now());
      items.push({actor,object,from,end,arm,heading,start:started.get(actor.signature)!});
    }
    return {
      tick(now:number) {
        let moving=false;
        const poses:Record<string,number[]>={};
        for(const {actor,object,from,end,arm,heading,start} of items) {
          const progress=!actor.motion||reducedMotion?1:Math.max(0,Math.min(1,(now-start)/TRAVEL_MS));
          object.position.lerpVectors(from,end,progress);
          if(arm) arm.rotation.y=(heading??0)-(1-progress)*0.9;
          if(actor.motion && progress<1) moving=true;
          poses[actor.id]=[object.position.x,object.position.y,object.position.z,arm?.rotation.y??0];
        }
        host.dataset.actorPoses=JSON.stringify(poses);
        host.dataset.actorAnimating=String(moving);
        return moving;
      },
      dispose() { /* The owning scene disposes this group's geometry, materials and textures. */ },
    };
  };
}
