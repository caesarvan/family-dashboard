import json
from pathlib import Path
from playwright.sync_api import sync_playwright

out = Path('test-results')
out.mkdir(exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
    page = browser.new_page(viewport={'width':1920,'height':1080}, device_scale_factor=1)
    errors=[]
    page.on('pageerror', lambda err: errors.append(str(err)))
    for label,width,height in [('tv-1080p',1920,1080),('tv-4k',3840,2160),('tv-720p',1280,720),('phone',390,844),('desktop',1440,1000)]:
        page.set_viewport_size({'width':width,'height':height})
        page.goto('http://127.0.0.1:8765/demo'+('?tv=1' if label.startswith('tv') else ''))
        page.wait_for_selector('.board')
        page.screenshot(path=str(out/(label+'.png')), full_page=True)
        metrics=page.evaluate('({width:innerWidth,height:innerHeight,scrollWidth:document.documentElement.scrollWidth,scrollHeight:document.documentElement.scrollHeight})')
        assert metrics['scrollWidth'] <= width, (label,metrics)
        if label.startswith('tv'): assert metrics['scrollHeight'] <= height, (label,metrics)
        print(label,metrics)
    page.goto('http://127.0.0.1:8765/')
    page.locator('input[type=password]').fill('testing-password-one')
    page.locator('button[type=submit]').click()
    page.wait_for_selector('.board')
    page.locator('[data-action=add][data-kind=tasks]').first.click()
    page.locator('dialog input[name=title]').fill('浏览器验证：采购清单')
    page.locator('dialog button[type=submit]').click()
    page.wait_for_selector('text=浏览器验证：采购清单')
    page.screenshot(path=str(out/'authenticated.png'), full_page=True)
    assert not errors, errors
    print(json.dumps({'pageErrors':errors,'taskCreate':'passed'},ensure_ascii=False))
    browser.close()
