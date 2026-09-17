import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AppState, Platform, ScrollView, StyleSheet, View, useWindowDimensions } from 'react-native';
import { useFocusEffect } from 'expo-router';
import { Button, Card, Text } from 'react-native-paper';
import TVBoard from '../ui/TVBoard';
import TVPhotoPlayer from '../ui/TVPhotoPlayer';
import { TVDiscarded, TVError, TVGeneration, readTVIdentity, readTVPair, readTVPairPoll, readTVSnapshot,
  readTVSpace, sameTVIdentity, tvIdentityKey, tvRequest, type TVIdentity, type TVPair,
  type TVSnapshot, type TVSpace } from '../lib/tv';
import { expoTokens } from '../ui/theme';

type Pairing = { pair: TVPair; space: TVSpace; deadline: number };
type Screen = { active: boolean; working: boolean; snapshot: TVSnapshot | null; identity: TVIdentity | null;
  space: TVSpace | null; code: string; seconds: number; message: string; now: number; verifiedAt: number; generation: number };
const initial = (): Screen => ({ active: false, working: false, snapshot: null, identity: null, space: null,
  code: '', seconds: 0, message: '正在核对电视连接…', now: Date.now(), verifiedAt: 0, generation: -1 });
const time = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' });

export default function TVScreen() {
  const { width } = useWindowDimensions(), [screen, setScreen] = useState<Screen>(initial);
  const generation = useRef(new TVGeneration()), present = useRef({ focused: false, foreground: true, pageHidden: false });
  const memory = useRef<{ identity: TVIdentity | null; pairing: Pairing | null; startAttempted: boolean;
    request: AbortController | null; nextRead: number }>({ identity: null, pairing: null, startAttempted: false, request: null, nextRead: 0 });
  const available = useCallback(() => Platform.OS === 'web' && present.current.focused && present.current.foreground && !present.current.pageHidden
    && typeof document !== 'undefined' && document.visibilityState !== 'hidden' && navigator.onLine !== false, []);

  const conceal = useCallback((message: string) => {
    generation.current.close();
    memory.current.request?.abort(); memory.current.request = null;
    // Pairing secret stays in memory for the original poll; no code or shared data remains rendered.
    setScreen(previous => ({ ...initial(), now: previous.now, message }));
  }, []);

  const run = useCallback(async (action: 'read' | 'start' = 'read') => {
    const gate = generation.current, ticket = gate.ticket(), current = memory.current;
    if (!available() || !gate.current(ticket) || current.request) return;
    const controller = new AbortController(); current.request = controller;
    const check = () => { gate.check(ticket); if (!available() || current.request !== controller) throw new TVDiscarded(); };
    const request = async (path: Parameters<typeof tvRequest>[0], body?: Record<string, unknown>) => {
      check(); const result = await tvRequest(path, controller.signal, body); check(); return result;
    };
    const hideCurrent = () => setScreen(previous => ({ ...previous, snapshot: null, identity: null, code: '', space: null, seconds: 0 }));
    const checkSpace = async (before: TVSpace) => {
      const after = readTVSpace(await request('/spaces/current'));
      if (before.id !== after.id) {
        current.pairing = null; current.startAttempted = true;
        throw new TVError('当前家庭已变化，请明确重新开始配对。', 409);
      }
      return after;
    };
    const install = async (actor: TVIdentity) => {
      if (!sameTVIdentity(current.identity, actor)) hideCurrent();
      current.identity = actor; current.pairing = null;
      const raw = await request('/state'), after = readTVIdentity(await request('/me'));
      if (!sameTVIdentity(actor, after) || !after) throw new TVError('电视身份已变化，旧内容已隐藏。', 409);
      const snapshot = readTVSnapshot(raw, after); check();
      current.identity = after; current.nextRead = Date.now() + 10_000;
      setScreen({ active: true, working: true, snapshot, identity: after, space: null, code: '', seconds: 0,
        message: '', now: Date.now(), verifiedAt: Date.now(), generation: ticket });
    };
    const showPair = (pairing: Pairing) => {
      check(); const seconds = Math.max(0, Math.ceil((pairing.deadline - performance.now()) / 1000));
      if (!seconds) throw new TVError('配对码已过期，请重新生成。', 410);
      current.nextRead = Date.now() + 5_000;
      setScreen({ ...initial(), active: true, working: true, space: pairing.space, code: pairing.pair.code,
        seconds, generation: ticket, message: '等待手机确认，这块电视会自动连接。' });
    };
    setScreen(previous => ({ ...previous, working: true }));
    try {
      const actor = readTVIdentity(await request('/me'));
      if (actor) { await install(actor); return; }
      if (current.identity) {
        hideCurrent();
        current.identity = null; current.pairing = null; current.startAttempted = true;
        throw new TVError('电视配对已撤销或到期，请重新生成配对码。', 401);
      }
      const space = readTVSpace(await request('/spaces/current'));
      if (current.pairing && current.pairing.space.id !== space.id) {
        current.pairing = null; current.startAttempted = true;
        throw new TVError('当前家庭已变化，原配对码已隐藏。请重新生成。', 409);
      }
      if (action === 'start' || (!current.startAttempted && !current.pairing)) {
        // Set the latch before the only non-idempotent request. StrictMode,
        // foreground recovery, failure and an expired code never retry this POST.
        current.startAttempted = true; current.pairing = null;
        const started = performance.now(), pair = readTVPair(await request('/pair/start', {}));
        const sameSpace = await checkSpace(space), after = readTVIdentity(await request('/me'));
        if (after) { await install(after); return; }
        current.pairing = { pair, space: sameSpace, deadline: started + pair.expiresIn * 1000 };
        showPair(current.pairing); return;
      }
      if (current.pairing) {
        const pairing = current.pairing;
        if (performance.now() >= pairing.deadline) throw new TVError('配对码已过期，请重新生成。', 410);
        const approved = readTVPairPoll(await request('/pair/poll', { secret: pairing.pair.secret }));
        await checkSpace(pairing.space);
        const after = readTVIdentity(await request('/me'));
        if (after) { await install(after); return; }
        if (approved) throw new TVError('手机已批准，请确认电视浏览器允许本站 Cookie，再核对连接。');
        showPair(pairing); return;
      }
      await checkSpace(space);
      current.nextRead = Date.now() + 10_000;
      setScreen({ ...initial(), active: true, working: true, space, generation: ticket,
        message: '尚未取得可用配对码。先前请求可能已产生未使用的码，它会自动到期；请明确重新生成。' });
    } catch (error) {
      if (error instanceof TVDiscarded || !gate.current(ticket) || !available()) return;
      if (error instanceof TVError && [401, 403, 409, 410].includes(error.status)) {
        current.identity = null; current.pairing = null; current.startAttempted = true;
      }
      current.nextRead = Date.now() + 5_000;
      setScreen({ ...initial(), active: true, working: true, generation: ticket,
        message: error instanceof TVError ? error.message : '暂时无法核对电视数据，旧内容已隐藏。' });
    } finally {
      if (current.request === controller) current.request = null;
      if (gate.current(ticket)) setScreen(previous => ({ ...previous, working: false }));
    }
  }, [available]);

  const resume = useCallback(() => {
    if (!available()) {
      conceal(Platform.OS !== 'web' ? '请在电视浏览器打开家庭地址 /tv。' : navigator.onLine === false
        ? '网络已断开，家庭内容与照片已隐藏。连接恢复后会重新核对。' : '屏幕暂时离开前台，内容已隐藏。');
      return;
    }
    if (generation.current.current(generation.current.ticket())) return;
    generation.current.open(); memory.current.nextRead = 0;
    setScreen(previous => ({ ...previous, active: true, message: '正在核对电视连接…' }));
    void run();
  }, [available, conceal, run]);

  useFocusEffect(useCallback(() => {
    present.current.focused = true;
    present.current.foreground = AppState.currentState !== 'background' && AppState.currentState !== 'inactive';
    present.current.pageHidden = false; resume();
    const app = AppState.addEventListener('change', value => {
      present.current.foreground = value === 'active'; resume();
    });
    const hide = () => { present.current.pageHidden = true; conceal('屏幕暂时离开前台，内容已隐藏。'); };
    const show = (event: PageTransitionEvent) => {
      if (!event.persisted && !present.current.pageHidden) return;
      present.current.pageHidden = false; conceal('正在重新核对电视连接…'); resume();
    };
    if (typeof window !== 'undefined') {
      document.addEventListener('visibilitychange', resume);
      window.addEventListener('offline', resume); window.addEventListener('online', resume);
      window.addEventListener('pagehide', hide); window.addEventListener('pageshow', show);
    }
    return () => {
      present.current.focused = false; conceal('正在重新核对电视连接…'); app.remove();
      if (typeof window !== 'undefined') {
        document.removeEventListener('visibilitychange', resume);
        window.removeEventListener('offline', resume); window.removeEventListener('online', resume);
        window.removeEventListener('pagehide', hide); window.removeEventListener('pageshow', show);
      }
    };
  }, [conceal, resume]));

  useEffect(() => {
    const timer = setInterval(() => {
      if (!available() || !generation.current.current(generation.current.ticket())) return;
      const pairing = memory.current.pairing, seconds = pairing ? Math.max(0, Math.ceil((pairing.deadline - performance.now()) / 1000)) : 0;
      if (pairing && !seconds) {
        memory.current.pairing = null;
        setScreen(previous => ({ ...previous, code: '', seconds: 0, message: '配对码已过期，请重新生成。', now: Date.now() }));
      } else setScreen(previous => ({ ...previous, now: Date.now(), seconds }));
      if (Date.now() >= memory.current.nextRead) void run();
    }, 1000);
    return () => clearInterval(timer);
  }, [available, run]);

  const unauthorized = useMemo(() => {
    const expected = screen.identity && tvIdentityKey(screen.identity), ticket = screen.generation;
    return () => {
      if (!expected || !generation.current.current(ticket) || !memory.current.identity
        || tvIdentityKey(memory.current.identity) !== expected) return;
      memory.current.identity = null; memory.current.pairing = null; memory.current.startAttempted = true;
      conceal('电视权限需要重新核对，内容已隐藏。'); resume();
    };
  }, [screen.identity, screen.generation, conceal, resume]);
  const ready = screen.active && screen.snapshot && screen.identity && generation.current.current(screen.generation);
  const font = Math.max(18, Math.min(30, width / 48)), heading = Math.max(28, Math.min(52, width / 30));
  return <View style={styles.screen} testID="tv-screen">
    {ready && screen.snapshot && screen.identity ? <View style={styles.board}>
      <TVBoard key={tvIdentityKey(screen.identity)} state={screen.snapshot.state} focus={screen.snapshot.display.focus}
        mode={screen.snapshot.display.calendarView} layout={screen.snapshot.display.layout} now={screen.now} />
      <Text style={styles.status} testID="tv-status">手机管理「电视与播放」 · 最近核对 {time.format(new Date(screen.verifiedAt))} · 每 10 秒更新</Text>
      <TVPhotoPlayer key={tvIdentityKey(screen.identity)} deviceId={screen.identity.id} active={!!ready} onUnauthorized={unauthorized} />
    </View> : <ScrollView contentContainerStyle={styles.center}>
      <Card mode="contained" style={[styles.pairCard, { width: Math.min(1100, Math.max(0, width - 48)) }]} testID="tv-pairing">
        <Card.Content style={{ paddingHorizontal: 32, paddingVertical: 36, gap: 24 }}>
          <Text accessibilityRole="header" style={[styles.heading, { fontSize: heading, lineHeight: heading * 1.2 }]}>连接这块电视</Text>
          {screen.space ? <Text style={{ fontSize: font, lineHeight: font * 1.5, color: expoTokens.body }}>{screen.space.name}</Text> : null}
          {screen.code ? <>
            <Text testID="tv-pair-code" accessibilityLabel={`电视配对码 ${screen.code}`} style={[styles.code, { fontSize: Math.min(88, width / 9), lineHeight: Math.min(112, width / 7) }]}>{screen.code.slice(0, 4)} {screen.code.slice(4)}</Text>
            <Text style={{ fontSize: font, color: expoTokens.body }}>{Math.floor(screen.seconds / 60)} 分 {String(screen.seconds % 60).padStart(2, '0')} 秒内有效</Text>
            <Text style={{ fontSize: font, lineHeight: font * 1.6 }}>在手机登录同一个家庭，打开「更多 → 电视与播放」，输入上方配对码并确认。</Text>
            {screen.space ? <Text selectable style={{ fontSize: Math.max(16, font - 4), lineHeight: font * 1.5, color: expoTokens.body }}>家庭入口：{typeof window !== 'undefined' ? window.location.origin : ''}{screen.space.entry}</Text> : null}
          </> : null}
          <Text accessibilityRole="text" testID="tv-status" style={{ fontSize: font, lineHeight: font * 1.5, color: expoTokens.body }}>{screen.message}</Text>
          {screen.active && !screen.code && !screen.working ? <View style={styles.actions}>
            <Button mode="contained" accessibilityLabel="重新生成配对码" onPress={() => void run('start')} contentStyle={{ minHeight: 52 }}>重新生成配对码</Button>
            <Button mode="outlined" accessibilityLabel="重新核对连接" onPress={() => void run()} contentStyle={{ minHeight: 52 }}>重新核对连接</Button>
          </View> : null}
          <Text style={{ fontSize: Math.max(16, font - 6), lineHeight: font * 1.5, color: expoTokens.body }}>电视仅展示家庭内容。照片需要本人单独允许在这块电视播放。</Text>
        </Card.Content>
      </Card>
    </ScrollView>}
  </View>;
}

const styles = StyleSheet.create({
  screen: { flex: 1, width: '100%', height: '100%', minHeight: 0, backgroundColor: expoTokens.canvas },
  board: { flex: 1, minHeight: 0, position: 'relative' },
  center: { flexGrow: 1, justifyContent: 'center', alignItems: 'center', padding: 24 },
  pairCard: { backgroundColor: expoTokens.canvasSoft, borderRadius: 32 },
  heading: { fontWeight: '600', color: expoTokens.ink },
  code: { fontWeight: '600', color: expoTokens.ink, letterSpacing: 4, paddingVertical: 12 },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 },
  status: { fontSize: 18, lineHeight: 26, color: expoTokens.body, backgroundColor: expoTokens.canvas, textAlign: 'center', padding: 8 },
});
