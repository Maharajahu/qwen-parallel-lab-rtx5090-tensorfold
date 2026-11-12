// Small geometric vocabulary. The local model still owns composition and detail.
export function createGeometrySDK(THREE) {
  function gable(width, depth, rise, roof, stone) {
    const x=width/2,z=depth/2;
    const geo=new THREE.BufferGeometry();
    geo.setAttribute('position',new THREE.Float32BufferAttribute([
      -x,0,-z, x,0,-z, 0,rise,-z, -x,0,z, x,0,z, 0,rise,z
    ],3));
    geo.setIndex([0,2,1,3,4,5, 0,1,4,0,4,3, 0,3,5,0,5,2, 1,2,5,1,5,4]);
    geo.addGroup(0,6,1);geo.addGroup(6,18,0);
    const flat=geo.toNonIndexed();geo.dispose();flat.computeVertexNormals();
    return new THREE.Mesh(flat,[roof,stone]);
  }
  function pointedShape(width,height) {
    const s=new THREE.Shape(),x=width/2,shoulder=height*.62;
    s.moveTo(-x,0);s.lineTo(x,0);s.lineTo(x,shoulder);
    s.quadraticCurveTo(x*.95,height*.83,0,height);
    s.quadraticCurveTo(-x*.95,height*.83,-x,shoulder);s.closePath();
    return s;
  }
  function arch(width,height,depth,thickness,material) {
    const x=width/2,t=thickness,shoulder=height*.62,s=new THREE.Shape();
    s.moveTo(-x,0);s.lineTo(-x,shoulder);
    s.quadraticCurveTo(-x*.95,height*.83,0,height);
    s.quadraticCurveTo(x*.95,height*.83,x,shoulder);s.lineTo(x,0);
    s.lineTo(x-t,0);s.lineTo(x-t,shoulder);
    s.quadraticCurveTo((x-t)*.95,height*.83-t,0,height-t);
    s.quadraticCurveTo(-(x-t)*.95,height*.83-t,-x+t,shoulder);
    s.lineTo(-x+t,0);s.closePath();
    const geo=new THREE.ExtrudeGeometry(s,{depth,bevelEnabled:false,curveSegments:12});
    geo.translate(0,0,-depth/2);
    return new THREE.Mesh(geo,material);
  }
  function window(width,height,frameMaterial,glassMaterial) {
    const group=new THREE.Group(),t=Math.min(width*.12,.18);
    group.add(arch(width,height,.24,t,frameMaterial));
    const glass=new THREE.Mesh(new THREE.ShapeGeometry(pointedShape(width-2*t,height-t),12),glassMaterial);
    glass.position.z=.135;group.add(glass);
    const bar=(w,h,x,y)=>{const m=new THREE.Mesh(new THREE.BoxGeometry(w,h,.08),frameMaterial);m.position.set(x,y,.18);group.add(m)};
    bar(width,t,0,0);bar(t*.65,height*.68,0,height*.34);bar(width-2*t,t*.65,0,height*.42);
    return group;
  }
  function solidRings(rings,sideMaterial,capMaterial) {
    // Accept either vertical order; do not let a reversed generated list invert
    // all faces or put the ground material on the bottom of the island.
    rings=[...rings].sort((a,b)=>a.reduce((s,p)=>s+p[1],0)/a.length-b.reduce((s,p)=>s+p[1],0)/b.length);
    const count=rings[0].length;
    if(count<3||rings.length<2||rings.some(r=>r.length!==count))throw Error('solidRings needs equal-size rings, bottom to top');
    const values=rings.flat(2),indices=[];
    for(let layer=0;layer<rings.length-1;layer++)for(let i=0;i<count;i++){
      const j=(i+1)%count,a=layer*count+i,b=layer*count+j,c=a+count,d=b+count;
      indices.push(a,c,d,a,d,b);
    }
    const sideCount=indices.length;
    for(const [layer,top]of [[0,false],[rings.length-1,true]]){
      const ring=rings[layer],center=[0,0,0];
      for(const p of ring)for(let k=0;k<3;k++)center[k]+=p[k]/count;
      const c=values.length/3;values.push(...center);
      for(let i=0;i<count;i++){const a=layer*count+i,b=layer*count+(i+1)%count;indices.push(c,top?b:a,top?a:b)}
    }
    const geo=new THREE.BufferGeometry();geo.setAttribute('position',new THREE.Float32BufferAttribute(values,3));geo.setIndex(indices);
    geo.addGroup(0,sideCount,0);geo.addGroup(sideCount,count*3,0);geo.addGroup(sideCount+count*3,count*3,1);
    const flat=geo.toNonIndexed();geo.dispose();flat.computeVertexNormals();
    return new THREE.Mesh(flat,[sideMaterial,capMaterial]);
  }
  return {gable,arch,window,solidRings};
}
