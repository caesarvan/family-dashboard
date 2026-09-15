"""Travel v2 forms in real local Flask/Edge; synthetic records, no cloud calls."""
import json
from pathlib import Path
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import create_app
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server, WSGIRequestHandler


class Quiet(WSGIRequestHandler):
    def log(self, *_args, **_kwargs):
        pass


def main():
    output = ROOT / 'test-results'
    output.mkdir(exist_ok=True)
    report = {'checks': [], 'pageErrors': [], 'externalRequests': [], 'productionWrites': 0, 'completed': False}
    with tempfile.TemporaryDirectory(prefix='journey-details-browser-') as folder:
        app = create_app({'TESTING': True, 'SECRET_KEY': 'synthetic-journey-details-key', 'DATA_DIR': folder,
                          'SESSION_COOKIE_SECURE': False, 'MEMBER1_PASSWORD': 'testing-password-one',
                          'MEMBER2_PASSWORD': 'testing-password-two'})
        server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=Quiet)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        origin = f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
                context = browser.new_context(viewport={'width': 1440, 'height': 1050})

                def guard(route):
                    if not route.request.url.startswith(origin + '/'):
                        report['externalRequests'].append(route.request.url.split('?', 1)[0])
                        route.abort()
                    else:
                        route.continue_()

                context.route('**/*', guard)
                assert context.request.post(origin + '/api/login', data={'username': 'member1', 'password': 'testing-password-one'}).status == 200
                headers = {'X-CSRF-Token': context.request.get(origin + '/api/me').json()['csrf']}
                page = context.new_page()
                page.on('pageerror', lambda error: report['pageErrors'].append(str(error)))
                page.goto(origin)
                expect(page.locator('.ps-home-board')).to_be_visible()
                page.evaluate('() => JourneyUI.create()')
                form = page.locator('#journey-form')
                core = form.locator('#journey-core-fields')
                core.locator('[name=title]').fill('跨日期线 · 合成旅行')
                core.locator('[name=start]').fill('2026-10-01')
                core.locator('[name=start]').press('Tab')
                core.locator('[name=end]').fill('2026-10-10')
                core.locator('[name=international]').select_option('true')
                core.locator('[name=budget]').fill('30000')
                destination = form.locator('.journey-destination')
                destination.locator('[name=country]').fill('日本 / 美国（合成）')
                destination.locator('[name=city]').fill('东京与檀香山')
                destination.locator('[name=arrival]').fill('2026-10-01')
                destination.locator('[name=departure]').fill('2026-10-10')
                page.locator('[data-journey=enable-details]').click()
                expect(form.locator('[name=referenceTimezone]')).to_be_visible()
                form.locator('.journey-destination [name=timeZone]').fill('Asia/Tokyo')

                def add(kind):
                    page.locator(f'[data-journey=add-detail][data-kind={kind}]').click()
                    return page.locator(f'.journey-v2-segment[data-kind={kind}]').last

                def fill(row, values):
                    for name, value in values.items():
                        locator = row.locator(f'[name="{name}"]')
                        if name in ('bookingState', 'datePolicy', 'activityMode'):
                            locator.select_option(value)
                        else:
                            locator.fill(value)

                flight = add('flight')
                fill(flight, {'title': '合成航班 HND → HNL', 'flightNumber': 'TEST-101',
                              'departure.airport': 'HND', 'departure.city': '东京', 'departure.local': '2026-10-03T00:30', 'departure.timeZone': 'Asia/Tokyo',
                              'arrival.airport': 'HNL', 'arrival.city': '檀香山', 'arrival.local': '2026-10-02T13:00', 'arrival.timeZone': 'Pacific/Honolulu'})
                stay = add('stay')
                fill(stay, {'title': '合成海边住宿', 'propertyName': 'Synthetic Ocean House', 'timeZone': 'Pacific/Honolulu',
                            'checkInDate': '2026-10-03', 'checkOutDate': '2026-10-05', 'bookingState': 'booked'})
                expect(stay.locator('.journey-stay-nights')).to_contain_text('2 晚')
                assert stay.locator('[name=datePolicy]').input_value() == 'fixed'
                activity = add('activity')
                fill(activity, {'title': '海边散步 · 可迁期', 'start.local': '2026-10-04T10:00', 'start.timeZone': 'Pacific/Honolulu',
                                'end.local': '2026-10-04T12:00', 'end.timeZone': 'Pacific/Honolulu', 'datePolicy': 'shift_with_trip'})
                cancelled = add('activity')
                fill(cancelled, {'title': '已取消的合成活动', 'start.local': '2026-10-04T13:00', 'start.timeZone': 'Pacific/Honolulu',
                                 'end.local': '2026-10-04T14:00', 'end.timeZone': 'Pacific/Honolulu', 'bookingState': 'cancelled'})
                # Choices follow edits immediately, including newly added rows, without resetting deliberate exclusions.
                form.locator('.journey-reschedule summary').click()
                options = form.locator('[data-shift-key]')
                expect(options).to_have_count(5)
                activity = form.locator('.journey-v2-segment[data-kind=activity]').first
                activity_option = form.locator(f'[data-shift-key="{activity.get_attribute("data-key")}"]')
                activity_option.uncheck()
                activity.locator('[name=title]').fill('海边散步 · 可迁期')
                activity.locator('[name=title]').press('Tab')
                expect(activity_option).not_to_be_checked()
                activity_option.check()
                stay_option = form.locator(f'[data-shift-key="{stay.get_attribute("data-key")}"]')
                expect(stay_option).to_be_disabled()
                expect(stay.locator('[name=datePolicy]')).to_be_disabled()
                stay.locator('[name=bookingState]').select_option('idea')
                stay.locator('[name=datePolicy]').select_option('shift_with_trip')
                expect(stay_option).to_be_enabled()
                stay.locator('[name=bookingState]').select_option('booked')
                expect(stay_option).to_be_disabled()
                temporary = add('activity')
                expect(options).to_have_count(6)
                temporary.locator('[data-journey=remove-detail]').click()
                expect(options).to_have_count(5)
                form.locator('.journey-reschedule summary').click()
                page.set_viewport_size({'width': 390, 'height': 844})
                flight.evaluate("node => node.scrollIntoView({block:'start'})")
                assert page.locator('#dialog').evaluate('(node) => node.scrollWidth <= node.clientWidth + 2')
                page.screenshot(path=str(output / 'journey-details-flight-editor-phone.png'))
                form.locator('[type=submit]').click()
                expect(page.locator('#journey-review-form')).to_be_visible()
                expect(page.locator('.journey-preview-itinerary')).to_contain_text('7 小时 30 分钟')
                expect(page.locator('.journey-preview-itinerary')).to_contain_text('Pacific/Honolulu')
                expect(page.locator('.journey-preview-itinerary')).to_contain_text('家庭时间')
                assert context.request.get(origin + '/api/journeys').json()['journeys'] == []
                page.screenshot(path=str(output / 'journey-details-preview-phone.png'))
                page.locator('#journey-apply').click()
                expect(page.locator('.journey-detail-top')).to_be_visible()
                first = context.request.get(origin + '/api/journeys').json()['journeys'][0]
                assert first['plan']['schemaVersion'] == 2 and first['trip']['title'] == '跨日期线 · 合成旅行'
                segments = {row['kind']: row for row in first['plan']['segments'] if row['bookingState'] != 'cancelled'}
                assert segments['flight']['departure']['instant'] == '2026-10-02T15:30:00Z'
                assert segments['flight']['arrival']['instant'] == '2026-10-02T23:00:00Z'
                assert segments['stay']['checkInTime'] == '' and segments['stay']['checkOutTime'] == ''
                assert len(first['events']) == 6
                report['checks'].append('Real v2 forms create flight across date line, two-night stay, activity and retained legacy day; cancelled item remains visibly marked with stable association; preview writes nothing')
                for width, height in [(390, 844), (1440, 1050)]:
                    page.set_viewport_size({'width': width, 'height': height})
                    page.locator('.journey-itinerary-item').filter(has_text='合成航班 HND → HNL').evaluate("node => node.scrollIntoView({block:'start'})")
                    assert page.locator('#dialog').evaluate('(node) => node.scrollWidth <= node.clientWidth + 2')
                    page.screenshot(path=str(output / f'journey-details-timeline-{width}.png'))
                page.locator('[data-journey=edit]').click()
                form = page.locator('#journey-form')
                form.locator('#journey-core-fields [name=start]').fill('2026-10-03')
                form.locator('#journey-core-fields [name=start]').press('Tab')
                assert form.locator('[name="departure.local"]').input_value().startswith('2026-10-03')
                form.locator('.journey-reschedule summary').click()
                page.locator('[data-journey=shift-details]').click()
                expect(page.locator('.journey-impact')).to_contain_text('移动 1 项')
                assert form.locator('[name="departure.local"]').input_value().startswith('2026-10-03')
                assert form.locator('[name=checkInDate]').input_value() == '2026-10-03'
                assert form.locator('.journey-v2-segment[data-kind=activity]').first.locator('[name="start.local"]').input_value().startswith('2026-10-06')
                form.locator('[type=submit]').click()
                expect(page.locator('#journey-apply')).to_be_enabled()
                page.locator('#journey-apply').click()
                expect(page.locator('.journey-detail-top')).to_be_visible()
                second = context.request.get(origin + '/api/journeys/' + first['id']).json()
                for kind in ('tasks', 'shopping', 'events'):
                    assert {item['id'] for item in first[kind]} == {item['id'] for item in second[kind]}
                report['checks'].append('Reschedule choices track added/removed rows and eligibility without losing exclusions; explicit shift moves only selected activity, leaves fixed/booked/cancelled/legacy dates and entity IDs stable')

                # An independent title edit must survive a budget-only plan change.
                event = next(item for item in second['events'] if item['workflowKey'] == 'segment:' + segments['flight']['key'])
                with app.app_context():
                    accounts = app.extensions['cloud_accounts']
                    with accounts.db() as connection:
                        raw = json.loads(connection.execute('SELECT data FROM entities WHERE id=?', (event['id'],)).fetchone()[0])
                        raw['title'] = '保留独立编辑的航班名称'
                        connection.execute('UPDATE entities SET data=?,revision=revision+1 WHERE id=?', (json.dumps(raw), event['id']))
                page.locator('[data-journey=edit]').click()
                page.locator('#journey-core-fields [name=budget]').fill('31000')
                page.locator('#journey-form [type=submit]').click()
                expect(page.locator('.journey-impact').filter(has_text='保留手工修改')).to_be_visible()
                page.locator('#journey-apply').click()
                expect(page.locator('.journey-detail-top')).to_be_visible()
                third = context.request.get(origin + '/api/journeys/' + first['id']).json()
                assert next(item for item in third['events'] if item['id'] == event['id'])['title'] == '保留独立编辑的航班名称'
                report['checks'].append('Manual event title survives budget-only update and preserved fields are visible before apply')

                page.locator('[data-journey=edit]').click()
                page.locator('.journey-v2-segment[data-kind=flight] [name=title]').fill('旅行草稿里的另一名称')
                page.locator('#journey-form [type=submit]').click()
                expect(page.locator('.journey-conflicts')).to_be_visible()
                expect(page.locator('#journey-apply')).to_be_disabled()
                page.locator('[data-conflict-field=title]').select_option('current')
                page.locator('[data-journey=repreview]').click()
                expect(page.locator('#journey-apply')).to_be_enabled()
                page.locator('#journey-apply').click()
                expect(page.locator('.journey-detail-top')).to_be_visible()
                report['checks'].append('Conflicting manual/event plan title requires explicit current/plan choice and repreview')

                # Nonexistent and ambiguous DST wall clocks require correction/choice.
                page.set_viewport_size({'width': 390, 'height': 844})
                page.locator('[data-journey=edit]').click()
                dst = add('activity')
                fill(dst, {'title': '柏林夏令时核对（合成）', 'start.local': '2026-03-29T02:30', 'start.timeZone': 'Europe/Berlin',
                           'end.local': '2026-03-29T04:30', 'end.timeZone': 'Europe/Berlin'})
                page.locator('#journey-form [type=submit]').click()
                expect(page.locator('.journey-error')).to_contain_text('不存在')
                assert dst.locator('[name="start.local"]').input_value() == '2026-03-29T02:30'
                fill(dst, {'start.local': '2026-10-25T02:30', 'end.local': '2026-10-25T03:30'})
                page.locator('#journey-form [type=submit]').click()
                expect(page.locator('[data-journey=choose-offset]')).to_have_count(2)
                page.locator('.journey-offset-choices').evaluate("node => node.scrollIntoView({block:'center'})")
                page.screenshot(path=str(output / 'journey-details-dst-choice-phone.png'))
                page.locator('[data-journey=choose-offset][data-offset="120"]').click()
                assert dst.locator('[name="start.offsetMinutes"]').input_value() == '120'
                page.locator('#journey-form [type=submit]').click()
                expect(page.locator('#journey-apply')).to_be_enabled()
                expect(page.locator('.journey-preview-itinerary')).to_contain_text('UTC+02:00')
                page.locator('#journey-apply').click()
                expect(page.locator('.journey-detail-top')).to_be_visible()
                report['checks'].append('DST nonexistent local time rejects without losing fields; Berlin repeated local time offers two offsets and explicit choice previews before save')

                page.locator('[data-journey=edit]').click()
                stay = page.locator('.journey-v2-segment[data-kind=stay]')
                fill(stay, {'timeZone': 'Europe/Berlin', 'checkInDate': '2026-10-25', 'checkOutDate': '2026-10-27', 'checkInTime': '02:30'})
                date_activity = add('activity')
                fill(date_activity, {'title': '日期型活动（合成）', 'activityMode': 'date'})
                fill(date_activity, {'dateRange.startDate': '2026-10-26', 'dateRange.endDateExclusive': '2026-10-27', 'timeZone': 'Europe/Berlin'})
                page.locator('#journey-form [type=submit]').click()
                expect(page.locator('[data-journey=choose-offset]')).to_have_count(2)
                page.locator('[data-journey=choose-offset][data-offset="60"]').click()
                assert stay.locator('[name=checkInOffsetMinutes]').input_value() == '60'
                page.locator('#journey-form [type=submit]').click()
                expect(page.locator('#journey-apply')).to_be_enabled()
                page.locator('#journey-apply').click()
                expect(page.locator('.journey-detail-top')).to_be_visible()
                after_dates = context.request.get(origin + '/api/journeys/' + first['id']).json()
                lodging = next(row for row in after_dates['plan']['segments'] if row['kind'] == 'stay')
                assert lodging['nights'] == 2 and lodging['checkInOffsetMinutes'] == 60
                date_row = next(row for row in after_dates['plan']['segments'] if row['title'] == '日期型活动（合成）')
                assert date_row['dateRange']['endDateExclusive'] == '2026-10-27' and date_row['timeZone'] == 'Europe/Berlin'
                report['checks'].append('Stay check-in DST ambiguity exposes its own offset choice; date-only activity explicitly preserves IANA zone and exclusive end date')

                # The plan may retain proposed clocks after explicitly keeping
                # an independently edited event; the detail must show the event.
                active = next(item for item in after_dates['events'] if item['workflowKey'] == 'segment:' + segments['activity']['key'])
                with app.extensions['cloud_accounts'].db() as connection:
                    raw = json.loads(connection.execute('SELECT data FROM entities WHERE id=?', (active['id'],)).fetchone()[0])
                    raw.update(start='2026-10-06T23:00:00Z', end='2026-10-07T01:00:00Z')
                    timing = raw['travelTiming']
                    timing.update(startLocal='2026-10-06T13:00:00', endLocal='2026-10-06T15:00:00')
                    connection.execute('UPDATE entities SET data=?,revision=revision+1 WHERE id=?', (json.dumps(raw), active['id']))
                page.locator('[data-journey=edit]').click()
                target = page.locator('.journey-v2-segment[data-kind=activity]').first
                fill(target, {'start.local': '2026-10-06T16:00', 'end.local': '2026-10-06T18:00'})
                page.locator('#journey-form [type=submit]').click()
                expect(page.locator('[data-conflict-field=timing]')).to_be_visible()
                page.locator('[data-conflict-field=timing]').select_option('current')
                page.locator('[data-journey=repreview]').click()
                expect(page.locator('#journey-apply')).to_be_enabled()
                page.locator('#journey-apply').click()
                expect(page.locator('.journey-detail-top')).to_be_visible()
                displayed = page.locator(f'.journey-itinerary-item[data-segment-key="{segments["activity"]["key"]}"]')
                expect(displayed).to_contain_text('2026-10-06 13:00:00')
                expect(displayed).to_contain_text('已保留当前日程的时间')
                expect(displayed).not_to_contain_text('2026-10-06 16:00:00')
                report['checks'].append('Explicit current-time conflict resolution displays effective saved event clock with a retained-time notice, not the differing plan clock')

                # A failed preview retains the entered form; stale apply exposes a
                # read-latest flow without silently replacing the member's draft.
                page.locator('[data-journey=edit]').click()
                page.locator('#journey-core-fields [name=budget]').fill('32100')
                context.route('**/api/journeys/preview', lambda route: route.fulfill(status=503, content_type='application/json', body='{"error":"合成预览暂不可用"}'))
                page.locator('#journey-form [type=submit]').click()
                expect(page.locator('.journey-error')).to_contain_text('合成预览暂不可用')
                assert page.locator('#journey-core-fields [name=budget]').input_value() == '32100'
                assert page.locator('.journey-v2-segment[data-kind=flight] [name="departure.timeZone"]').input_value() == 'Asia/Tokyo'
                context.unroute('**/api/journeys/preview')
                page.locator('#journey-form [type=submit]').click()
                expect(page.locator('#journey-apply')).to_be_enabled()
                latest = context.request.get(origin + '/api/journeys/' + first['id']).json()
                remote_plan = json.loads(json.dumps(latest['plan']))
                remote_plan['saved'] = 10000
                p = context.request.post(origin + '/api/journeys/preview', data={'journeyId': latest['id'], 'revision': latest['revision'], 'plan': remote_plan}, headers=headers)
                assert p.status == 200
                changed = context.request.post(origin + '/api/journeys/apply', data={'previewToken': p.json()['previewToken'], 'idempotencyKey': 'parallel-plan-update'}, headers=headers)
                assert changed.status == 200
                page.locator('#journey-apply').click()
                expect(page.locator('[data-journey=latest-draft]')).to_be_visible()
                page.locator('[data-journey=latest-draft]').click()
                expect(page.locator('[data-journey=rebase-draft]')).to_be_visible()
                page.locator('[data-journey=rebase-draft]').click()
                expect(page.locator('#journey-apply')).to_be_enabled()
                expect(page.locator('.journey-review-hero')).to_contain_text('32,100')
                page.locator('#journey-apply').click()
                expect(page.locator('.journey-detail-top')).to_be_visible()
                final = context.request.get(origin + '/api/journeys/' + first['id']).json()
                assert final['budget']['total'] == 3210000
                report['checks'].append('503 preview keeps complete draft; concurrent plan apply returns 409, read-latest preserves draft and explicit repreview succeeds')

                page.evaluate('() => JourneyUI.create()')
                page.locator('#journey-core-fields [name=title]').fill('保留旧版日期计划')
                page.locator('.journey-destination [name=city]').fill('上海')
                context.route('**/api/journeys/templates', lambda route: route.fulfill(status=200, content_type='application/json', body='{"supportedSchemaVersions":[1]}'))
                page.locator('[data-journey=enable-details]').click()
                expect(page.locator('.journey-error')).to_contain_text('尚未支持旅行细项')
                assert page.locator('#journey-core-fields [name=title]').input_value() == '保留旧版日期计划'
                expect(page.locator('[name=referenceTimezone]')).to_have_count(0)
                context.unroute('**/api/journeys/templates')
                page.locator('#journey-form [type=submit]').click()
                expect(page.locator('#journey-apply')).to_be_enabled()
                page.locator('#journey-apply').click()
                expect(page.locator('.journey-detail-top')).to_be_visible()
                legacy = next(value for value in context.request.get(origin + '/api/journeys').json()['journeys'] if value['plan']['title'] == '保留旧版日期计划')
                original_ids = {value['id'] for value in legacy['events']}
                page.locator('[data-journey=edit]').click()
                page.locator('[data-journey=enable-details]').click()
                expect(page.locator('.journey-v2-segment[data-kind=legacy_day]')).to_have_count(1)
                page.locator('#journey-form [type=submit]').click()
                expect(page.locator('#journey-apply')).to_be_enabled()
                page.locator('#journey-apply').click()
                expect(page.locator('.journey-detail-top')).to_be_visible()
                upgraded = context.request.get(origin + '/api/journeys/' + legacy['id']).json()
                assert upgraded['plan']['schemaVersion'] == 2 and upgraded['plan']['segments'][0]['kind'] == 'legacy_day'
                assert original_ids == {value['id'] for value in upgraded['events']}
                page.locator('[data-journey=edit]').click()
                page.locator('[name=changeKind]').select_option('activity')
                converted = page.locator('.journey-v2-segment[data-kind=activity]')
                fill(converted, {'start.local': upgraded['plan']['start'] + 'T09:30', 'end.local': upgraded['plan']['start'] + 'T11:30'})
                page.locator('#journey-form [type=submit]').click()
                expect(page.locator('#journey-apply')).to_be_enabled()
                page.locator('#journey-apply').click()
                expect(page.locator('.journey-detail-top')).to_be_visible()
                converted_plan = context.request.get(origin + '/api/journeys/' + legacy['id']).json()
                assert original_ids == {value['id'] for value in converted_plan['events']}
                assert converted_plan['plan']['segments'][0]['kind'] == 'activity'
                report['checks'].append('Old server capability blocks v2 submission without dropping draft; persisted v1 explicitly upgrades preserving legacy IDs and can become a timed activity through fields with same IDs')

                demo = browser.new_context(viewport={'width': 390, 'height': 844})
                demo.route('**/*', guard)
                demo_page = demo.new_page()
                demo_page.on('pageerror', lambda error: report['pageErrors'].append(str(error)))
                writes = []
                demo_page.on('request', lambda request: writes.append(request.url) if request.method not in ('GET', 'HEAD') else None)
                demo_page.goto(origin + '/demo')
                expect(demo_page.locator('.ps-home-board')).to_be_visible()
                demo_page.evaluate('() => JourneyUI.create()')
                demo_page.locator('#journey-core-fields [name=title]').fill('演示旅行细项')
                demo_page.locator('.journey-destination [name=city]').fill('演示目的地')
                demo_page.locator('[data-journey=enable-details]').click()
                demo_page.locator('[data-journey=add-detail][data-kind=activity]').click()
                demo_page.locator('.journey-v2-segment[data-kind=activity] [name=title]').fill('演示活动')
                demo_page.locator('#journey-form [type=submit]').click()
                expect(demo_page.locator('#journey-review-form')).to_be_visible()
                expect(demo_page.locator('#journey-apply')).to_be_disabled()
                assert not writes, writes
                assert demo_page.locator('#dialog').evaluate('(node) => node.scrollWidth <= node.clientWidth + 2')
                demo.close()
                report['checks'].append('Phone demo edits v2 forms and previews only with disabled apply; zero write requests')
                assert not report['pageErrors'], report['pageErrors']
                assert not report['externalRequests'], report['externalRequests']
                report['completed'] = True
                context.close()
                browser.close()
        finally:
            server.shutdown()
            worker.join(timeout=5)
            server.server_close()
            (output / 'journey-details-browser-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
