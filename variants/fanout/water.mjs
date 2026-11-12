// Planar scene reflection from Three.js Reflector, with small animated water ripples.
export function createWaterFactory(THREE, Reflector, palette, addUpdate) {
  return (size=800)=>{
    const shader={
      uniforms:{color:{value:null},tDiffuse:{value:null},textureMatrix:{value:null},time:{value:0},haze:{value:new THREE.Color(palette.sky)}},
      vertexShader:`uniform mat4 textureMatrix; varying vec4 vUv; varying vec3 vWorld;
        void main(){vUv=textureMatrix*vec4(position,1.0);vWorld=(modelMatrix*vec4(position,1.0)).xyz;
          gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}`,
      fragmentShader:`uniform vec3 color;uniform vec3 haze;uniform sampler2D tDiffuse;uniform float time;
        varying vec4 vUv;varying vec3 vWorld;
        void main(){
          vec2 p=vWorld.xz;
          vec2 wave=vec2(sin(p.x*.19+p.y*.07+time*.7)+sin(p.y*.31-time*.9),
                         cos(p.y*.16+p.x*.05-time*.6)+sin(p.x*.23+time*.5));
          vec2 uv=vUv.xy/vUv.w+wave*.0015;
          vec3 reflected=texture2D(tDiffuse,clamp(uv,vec2(.001),vec2(.999))).rgb;
          vec3 view=normalize(cameraPosition-vWorld);vec3 normal=normalize(vec3(wave.x*.025,1.,wave.y*.025));
          float fresnel=.32+.48*pow(1.-max(dot(view,normal),0.),3.);
          vec3 c=mix(color*.65,reflected,fresnel);
          float glint=pow(max(dot(reflect(normalize(vec3(.4,-1.,-.3)),normal),view),0.),100.);
          c+=vec3(.48,.58,.68)*glint*.18;
          c=mix(c,haze,smoothstep(170.,600.,length(cameraPosition-vWorld))*.8);
          gl_FragColor=vec4(c,1.);
          #include <tonemapping_fragment>
          #include <colorspace_fragment>
        }`
    };
    const mesh=new Reflector(new THREE.PlaneGeometry(size,size),{color:palette.water,textureWidth:1024,textureHeight:1024,multisample:0,clipBias:.003,shader});
    mesh.rotation.x=-Math.PI/2;
    addUpdate((dt,time)=>{mesh.material.uniforms.time.value=time});
    return mesh;
  };
}
