"""Isolated static calendar smoke test; never contacts production or changes household data."""
import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'test-results'
OUT.mkdir(exist_ok=True)


class PreviewHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path.split('?')[0] in ('/demo', '/'):
            html = (ROOT / 'static/index.html').read_text(encoding='utf-8')
            assets = ''
            if 'calendar.css' not in html:
                assets += '<link rel="stylesheet" href="/static/calendar.css">'
            if 'calendar-ui.js' not in html:
                assets += '<script src="/static/calendar-ui.js" defer></script>'
            # Supports reviewing this module independently before root integrates its entrypoints.
            assets += '<script>document.addEventListener("DOMContentLoaded",()=>{calendarCard=()=>CalendarViews.renderCard();renderBoard()})</script>'
            payload = html.replace('</head>', assets + '</head>').encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(payload)
        else:
            super().do_GET()


server = ThreadingHTTPServer(('127.0.0.1', 0), partial(PreviewHandler, directory=str(ROOT)))
threading.Thread(target=server.serve_forever, daemon=True).start()
try:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
        records, errors = [], []
        page = browser.new_page(viewport={'width':1920, 'height':1080})
        page.on('pageerror', lambda err: errors.append(str(err)))
        page.add_init_script('localStorage.clear()')
        for name, width, height in [('tv-720p',1280,720),('tv-1080p',1920,1080),('tv-4k',3840,2160),('phone',390,844),('desktop',1440,1000)]:
            page.set_viewport_size({'width':width,'height':height})
            page.goto(f'http://127.0.0.1:{server.server_port}/demo' + ('?tv=1' if name.startswith('tv') else ''))
            page.wait_for_selector('.cv-card')
            assert page.locator('[data-calendar-mode=today]').first.get_attribute('aria-pressed') == 'true'
            page.evaluate('''() => {
                const days = CalendarViews.helpers.rangeDays('week', dateKey());
                data.events = days.flatMap((day, i) => [
                    {id:'a'+i,title:'方案评审与本周工作安排',start:day+'T10:00:00+08:00',end:day+'T11:30:00+08:00',location:'办公室 · 第二会议室',owner:'member1'},
                    {id:'b'+i,title:i===2?'一起吃晚饭，顺便采购周末用品':'预约运动与课程',start:day+'T18:00:00+08:00',end:day+'T19:00:00+08:00',location:i===2?'社区附近的餐厅':'运动中心',owner:i===2?'shared':'member2'}
                ]);
                data.events.push({id:'all',title:'杭州出差',start:days[3]+'T00:00:00+08:00',end:days[5]+'T00:00:00+08:00',owner:'member1',location:'杭州',allDay:true});
                renderBoard();
            }''')
            for mode in ('today','week','around'):
                page.locator(f'[data-calendar-mode={mode}]').first.click()
                assert page.locator('.cv-card').get_attribute('class').find('cv-'+mode) >= 0
                metrics = page.evaluate('''() => ({width:innerWidth,height:innerHeight,scrollWidth:document.documentElement.scrollWidth,scrollHeight:document.documentElement.scrollHeight,cards:[...document.querySelectorAll('.board>.card')].map(el=>({class:el.className,bottom:el.getBoundingClientRect().bottom,overflowY:el.scrollHeight-el.clientHeight}))})''')
                assert metrics['scrollWidth'] <= width, (name, mode, metrics)
                if name.startswith('tv'):
                    assert metrics['scrollHeight'] <= height, (name, mode, metrics)
                    assert len(metrics['cards']) == 5
                    assert all(card['bottom'] <= height and card['overflowY'] <= 2 for card in metrics['cards']), (name, mode, metrics)
                if mode == 'week':
                    page.screenshot(path=str(OUT / f'calendar-{name}.png'), full_page=True)
                    first_day = page.locator('.cv-day-heading').first.get_attribute('data-calendar-day')
                    page.locator('.cv-day-heading').first.click()
                    assert page.locator('dialog').is_visible()
                    assert page.locator('.cv-manager .cv-event').count() == 2
                    page.locator('dialog [data-action=close]').click()
                    page.locator('[data-calendar-move="1"]').first.click()
                    next_day = page.locator('.cv-day-heading').first.get_attribute('data-calendar-day')
                    assert first_day != next_day
                    page.locator('[data-calendar-reset]').first.click()
                    assert page.locator('.cv-day-heading').first.get_attribute('data-calendar-day') == first_day
                records.append({'viewport':name,'mode':mode,**metrics})
        playback_checks = []
        for width, height in [(1280,720),(1920,1080),(3840,2160)]:
            for mode in ('today','week','around'):
                tv = browser.new_page(viewport={'width':width,'height':height})
                tv.on('pageerror', lambda err: errors.append(str(err)))
                tv.add_init_script('localStorage.clear()')
                tv.clock.install()
                tv.goto(f'http://127.0.0.1:{server.server_port}/demo?tv=1')
                tv.wait_for_selector('.cv-card')
                tv.evaluate('''() => {
                    data.events = CalendarViews.helpers.rangeDays('around',dateKey()).flatMap(day => Array.from({length:10},(_,i)=>({
                        id:day+'-'+i,title:'事件 '+i+'：'+('讨论本次方案与后续安排，完整说明应当在屏幕上自动展示。'.repeat(6)),
                        start:day+'T'+String(8+i).padStart(2,'0')+':00:00+08:00',end:day+'T'+String(9+i).padStart(2,'0')+':00:00+08:00',
                        location:'上海办公室 · '+('会议区域与地址说明。'.repeat(8)),owner:i%2?'member2':'member1'
                    })));
                    renderBoard();
                }''')
                tv.locator(f'[data-calendar-mode={mode}]').first.click()
                selector = '.cv-today-events' if mode == 'today' else '.cv-day.cv-today .cv-day-events'
                seen = set()
                for page_number in range(4):
                    tv.clock.run_for(150)
                    titles = tv.locator(selector+' .cv-event-title').all_text_contents()
                    seen.update(int(title.split('：')[0].split()[-1]) for title in titles)
                    if page_number == 0:
                        start = tv.locator(selector).evaluate('(el)=>({top:el.scrollTop,extra:el.scrollHeight-el.clientHeight})')
                        assert start['extra'] > 0 and start['top'] == 0, (width,mode,start)
                        tv.clock.fast_forward(18000)
                        finish = tv.locator(selector).evaluate('(el)=>({top:el.scrollTop,extra:el.scrollHeight-el.clientHeight})')
                        assert abs(finish['top'] - finish['extra']) <= 2, (width,mode,finish)
                        tv.clock.fast_forward(2100)
                    else:
                        tv.clock.fast_forward(20100)
                assert seen == set(range(10)), (width,mode,seen)
                assert tv.evaluate('document.documentElement.scrollWidth <= innerWidth && document.documentElement.scrollHeight <= innerHeight')
                playback_checks.append({'width':width,'mode':mode,'seen':sorted(seen),'longTextAutoScroll':'passed'})
                tv.close()
        assert not errors, errors
        (OUT / 'calendar-browser.json').write_text(json.dumps({'errors':errors,'checks':records,'playback':playback_checks},ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'checks':len(records),'tvPlaybackChecks':len(playback_checks),'errors':errors},ensure_ascii=False))
        browser.close()
finally:
    server.shutdown()
