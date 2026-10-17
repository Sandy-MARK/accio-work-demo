import http from 'node:http';
import {readFile,stat} from 'node:fs/promises';
import {resolve,extname,dirname,sep} from 'node:path';
import {fileURLToPath} from 'node:url';
const root=resolve(dirname(fileURLToPath(import.meta.url)),'dist');
const port=Number(process.env.PORT||4174);
const api=new URL(process.env.API_BASE||'http://127.0.0.1:8000');
const types={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.json':'application/json; charset=utf-8','.png':'image/png','.jpeg':'image/jpeg','.jpg':'image/jpeg','.webp':'image/webp','.svg':'image/svg+xml','.ico':'image/x-icon'};
function proxy(req,res){const up=http.request({hostname:api.hostname,port:api.port,path:req.url,method:req.method,headers:{...req.headers,host:api.host}},r=>{res.writeHead(r.statusCode,r.headers);r.pipe(res)});up.on('error',()=>{res.writeHead(502,{'Content-Type':'application/json; charset=utf-8'});res.end(JSON.stringify({detail:'知识库服务未启动'}))});req.pipe(up)}
http.createServer(async(req,res)=>{if(req.url.startsWith('/api/'))return proxy(req,res);try{const pathname=decodeURIComponent(new URL(req.url,'http://localhost').pathname);const file=resolve(root,'.'+(pathname==='/'?'/index.html':pathname));if(file!==root&&!file.startsWith(root+sep)){res.writeHead(403);res.end('Forbidden');return}if(!(await stat(file)).isFile())throw new Error();const content=await readFile(file);res.writeHead(200,{'Content-Type':types[extname(file)]||'application/octet-stream','Cache-Control':'no-cache'});res.end(content)}catch{res.writeHead(404,{'Content-Type':'text/plain; charset=utf-8'});res.end('Not found')}}).listen(port,'127.0.0.1',()=>console.log(`Accio Work: http://localhost:${port}（知识库接口转发到 ${api.origin}）`));
