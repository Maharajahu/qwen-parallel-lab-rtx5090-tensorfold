"""Exercise the generated page and return a bounded, honest browser receipt."""
import json,sys,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright

def inspect(directory):
    source=(directory/'index.html').read_bytes()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path!='/':self.send_error(404);return
            self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(source)));self.end_headers();self.wfile.write(source)
        def log_message(self,*_):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
    errors=[];started=time.perf_counter()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,args=['--use-angle=d3d11'])
            page=browser.new_page(viewport={'width':1920,'height':1080},device_scale_factor=1)
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}/',wait_until='domcontentloaded')
            page.wait_for_function('window.__fanout?.ready && window.__fanout.frames>=60',timeout=30000)
            page.screenshot(path=str(directory/'browser-preview.png'))
            buttons=page.get_by_role('button').all_text_contents()
            controls=[]
            for label in ['Pause','Reset view']:
                button=page.get_by_role('button',name=label,exact=True)
                if button.count():button.click();controls.append(label)
            resume=page.get_by_role('button',name='Play',exact=True)
            if resume.count():resume.click();controls.append('Play')
            page.mouse.move(900,550);page.mouse.down();page.mouse.move(1100,620,steps=12);page.mouse.up();page.mouse.wheel(0,-160)
            page.wait_for_timeout(600)
            receipt=page.evaluate('window.__fanout');receipt.update({'page_errors':errors,'buttons':buttons,'controls_exercised':controls+['orbit drag','scroll zoom'],'seconds':time.perf_counter()-started})
            (directory/'browser-receipt.json').write_text(json.dumps(receipt,indent=2));browser.close()
            if errors or receipt['errors'] or len(receipt['parts'])!=8:raise RuntimeError('Browser scene validation failed: '+json.dumps(receipt))
            return {'ready':True,'parts':8,'frames':receipt['frames'],'page_errors':errors,'seconds':receipt['seconds'],'buttons':buttons,'screenshot':'browser-preview.png'}
    finally:server.shutdown();server.server_close()

if __name__=='__main__':print(json.dumps(inspect(Path(sys.argv[1]).resolve())),flush=True)
