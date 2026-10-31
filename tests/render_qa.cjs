// Optional developer-only raster QA: npm install --no-save sharp
const fs=require('fs'),path=require('path'),assert=require('assert');
const sharp=require('sharp');
const root=path.resolve(__dirname,'..');
const decode=s=>s.replaceAll('&lt;','<').replaceAll('&gt;','>').replaceAll('&quot;','"').replaceAll('&#x27;',"'").replaceAll('&amp;','&');
const escape=s=>s.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
(async()=>{
 const counts=[];
 for(const n of ['A','B','C','../tests/overflow']){
  const file=path.join(root,'examples',n+'.svg'),svg=fs.readFileSync(file,'utf8');
  await sharp(file).png().toFile(path.join(root,'examples',n+'.png'));
  const boxes=[];
  const clips={};
  for(const c of svg.matchAll(/<clipPath id="([^"]+)"><rect x="([^"]+)" y="([^"]+)" width="([^"]+)" height="([^"]+)"/g))clips[c[1]]={x:+c[2],y:+c[3],w:+c[4],h:+c[5]};
  const groups=[...svg.matchAll(/<g[^>]*clip-path="url\(#([^)]+)\)"[^>]*>([\s\S]*?)<\/g>/g)];
  for(const match of svg.matchAll(/<text\b([^>]*)>([^<]*)<\/text>/g)){
   const attrs=match[1], value=decode(match[2]);
   const get=k=>(attrs.match(new RegExp('(?:^| )'+k+'="([^"]*)"'))||[])[1];
   const x=Number(get('x')), y=Number(get('y')), size=Number(get('font-size')||20);
   const meta=await sharp({text:{text:escape(value),font:'PingFang TC '+size,dpi:72,rgba:true}}).metadata();
   const width=meta.width, height=meta.height;
   let left=x;if(get('text-anchor')==='middle')left-=width/2;if(get('text-anchor')==='end')left-=width;
   const box={left,right:left+width,top:y-size*.8,bottom:y+size*.2,value};
   assert(box.left>=0&&box.right<=1600&&box.top>=0&&box.bottom<=1000,'Canvas text overflow: '+value);
   for(const other of boxes){
    const overlapX=Math.min(box.right,other.right)-Math.max(box.left,other.left);
    const overlapY=Math.min(box.bottom,other.bottom)-Math.max(box.top,other.top);
    assert(overlapX<=1||overlapY<=1,'Text collision: '+value+' / '+other.value);
   }
   for(const group of groups){
    if(group[2].includes(match[0])){
     const c=clips[group[1]];
     assert(box.left>=c.x-1&&box.right<=c.x+c.w+1&&box.top>=c.y-1&&box.bottom<=c.y+c.h+1,'Panel overflow: '+value);
    }
   }
   boxes.push(box);
  }
  counts.push(n+': '+boxes.length+' text nodes');
 }
 const thumbs=await Promise.all(['A','B','C'].map(n=>sharp(path.join(root,'examples',n+'.png')).resize(800,500).toBuffer()));
 await sharp({create:{width:2400,height:500,channels:3,background:'white'}}).composite(thumbs.map((input,i)=>({input,left:i*800,top:0}))).png().toFile(path.join(root,'examples/comparison.png'));
 console.log('Rendered A/B/C; raster font-metric text bounds/collisions passed. '+counts.join('; '));
 console.log('Sharp '+sharp.versions.sharp+'; librsvg '+sharp.versions.rsvg);
})().catch(e=>{console.error(e);process.exitCode=1});
