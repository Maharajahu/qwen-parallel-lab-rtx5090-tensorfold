"""Exercise the generated scene and controls, with software rendering during inference."""
import argparse
import json
from pathlib import Path
import re
import time

from playwright.sync_api import sync_playwright


def inspect(work, hardware=False):
    started = time.monotonic()
    errors, checks = [], {}
    receipt = {'passed': False, 'renderer': 'd3d11' if hardware else 'swiftshader', 'checks': checks}
    def concise(error):
        return re.sub(r'data:text/javascript;base64,[A-Za-z0-9+/=]+', '[three.js]', str(error))[-2500:]
    source = (work / 'site/index.html').read_text(encoding='utf-8')
    marker = source.rfind('</script>')
    source = source[:marker] + '\nwindow.__validation={state,spherical,scene,camera};\n' + source[marker:]
    try:
        with sync_playwright() as playwright:
            args = ['--use-angle=d3d11'] if hardware else ['--use-angle=swiftshader', '--enable-unsafe-swiftshader']
            browser = playwright.chromium.launch(headless=True, args=args)
            page = browser.new_page(viewport={'width': 1280 if hardware else 800, 'height': 720 if hardware else 450})
            page.on('pageerror', lambda e: errors.append(concise(e)))
            try:
                page.set_content(source, wait_until='load')
                page.wait_for_function('window.__fanout && (window.__fanout.errors.length || window.__fanout.frames >= 3)', timeout=45000)
                state = page.evaluate('window.__fanout')
                checks['eight_components'] = sorted(state['parts']) == list(range(8))
                checks['render_ready'] = state['ready']
                errors.extend(concise(e) for e in state['errors'])
                if errors or not all(checks.values()):
                    raise RuntimeError('Scene initialization failed')
                page.get_by_role('button', name='Pause motion', exact=True).click()
                checks['pause'] = page.evaluate('window.__validation.state.paused') is True
                before = page.evaluate('window.__validation.state.time')
                page.wait_for_timeout(200)
                checks['time_stays_paused'] = page.evaluate('window.__validation.state.time') == before
                page.get_by_role('button', name='Resume motion', exact=True).click()
                checks['resume'] = page.evaluate('window.__validation.state.paused') is False
                page.get_by_role('button', name='Lumos', exact=True).click()
                checks['lumos_action'] = True
                start = page.evaluate('({theta:__validation.spherical.theta,radius:__validation.spherical.radius})')
                page.mouse.move(400, 230); page.mouse.down(); page.mouse.move(490, 260, steps=6); page.mouse.up()
                checks['orbit'] = page.evaluate('__validation.spherical.theta') != start['theta']
                page.mouse.wheel(0, -160); page.wait_for_timeout(200)
                checks['zoom'] = page.evaluate('__validation.spherical.radius') != start['radius']
                page.get_by_role('button', name='Reset view', exact=True).click()
                checks['reset_view'] = page.evaluate('Math.abs(__validation.spherical.theta - ' + str(start['theta']) + ') < 1e-8')
                page.wait_for_timeout(200)
                state = page.evaluate('window.__fanout')
                errors.extend(concise(e) for e in state['errors'])
                receipt['scene'] = {k: v for k, v in state.items() if k != 'errors'}
                page.screenshot(path=str(work / 'site/browser-preview.png'))
                checks['no_browser_errors'] = not errors
                receipt['passed'] = bool(checks) and all(checks.values())
            finally:
                browser.close()
    except Exception as error:
        receipt['error'] = concise(error)
    receipt.update(errors=errors, seconds=time.monotonic() - started)
    (work / 'browser-receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps(receipt, ensure_ascii=False))
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--hardware', action='store_true')
    parser.add_argument('--work', type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    raise SystemExit(0 if inspect(args.work.resolve(), args.hardware)['passed'] else 1)
