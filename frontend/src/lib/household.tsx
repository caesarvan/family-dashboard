import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { AppState } from 'react-native';
import { ApiError, request } from './api';
import { acceptHomeLayout } from './homeLayout';
import { FamilyState, HomeLayout, Member, Preferences } from './types';

type Session = { user: Member | null; csrf?: string | null };
const signature = (session: Session) => JSON.stringify([session.user?.role, session.user?.householdId, session.user?.id, session.user?.auth_version, session.csrf]);
const defaults: Preferences = { theme: 'light', density: 'comfortable', homeView: 'today' };
const defaultLayout: HomeLayout = { revision: 0, order: ['calendar', 'finance', 'tasks', 'shopping', 'trips'], hidden: [] };

function useHouseholdState() {
  const [session, setSession] = useState<Session>({ user: null });
  const [state, setState] = useState<FamilyState | null>(null);
  const [preferences, setPreferences] = useState<Preferences>(defaults);
  const [layout, setLayout] = useState<HomeLayout>(defaultLayout);
  const [focus, setFocus] = useState('');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [online, setOnline] = useState(true);
  const [notice, setNotice] = useState('');
  const current = useRef<Session>({ user: null });
  const sequence = useRef(0);
  const mounted = useRef(true);
  const reading = useRef<Promise<void> | null>(null);
  const authTransition = useRef(false);
  const preferenceWriting = useRef(false);
  const preferencesRef = useRef(defaults);
  const layoutRef = useRef(defaultLayout);
  const applyLayout = useCallback((next: HomeLayout, expectedIdentity: string): boolean => {
    if (!mounted.current || current.current.user?.role !== 'member') return false;
    const accepted = acceptHomeLayout(layoutRef.current, next, expectedIdentity, signature(current.current));
    if (!accepted) return false;
    layoutRef.current = accepted; setLayout(accepted); return true;
  }, []);

  const refresh = useCallback(async () => {
    if (authTransition.current) return;
    if (reading.current) return reading.current;
    const ticket = ++sequence.current;
    const job = (async () => {
      setRefreshing(true);
      try {
        const next = await request<Session>('/me');
        if (!mounted.current || ticket !== sequence.current) return;
        const changed = signature(next) !== signature(current.current);
        if (changed) { setState(null); setPreferences(defaults); layoutRef.current=defaultLayout; setLayout(defaultLayout); setFocus(next.user?.id || ''); }
        current.current = next; setSession(next);
        if (!next.user || next.user.role !== 'member') { setState(null); setError(''); setOnline(true); return; }
        const [snapshot, prefs, cards] = await Promise.all([
          request<FamilyState>('/state'), request<Preferences>('/preferences'), request<HomeLayout>('/dashboard-layout'),
        ]);
        if (!mounted.current || ticket !== sequence.current || signature(next) !== signature(current.current)) return;
        setState(snapshot); preferencesRef.current=prefs; setPreferences(prefs); applyLayout(cards, signature(next));
        setFocus(value => snapshot.people.some(person => person.id === value) ? value : next.user!.id);
        setError(''); setOnline(true);
      } catch (failure) {
        if (!mounted.current || ticket !== sequence.current) return;
        if (failure instanceof ApiError && [401, 403].includes(failure.status)) {
          current.current = { user: null }; setSession({ user: null }); setState(null); setPreferences(defaults); layoutRef.current=defaultLayout; setLayout(defaultLayout);
        }
        setOnline(false); setError(failure instanceof Error ? failure.message : '暂时无法读取家庭数据');
      } finally { if (mounted.current && ticket === sequence.current) { setLoading(false); setRefreshing(false); } }
    })();
    reading.current = job;
    try { await job; } finally { if (reading.current === job) reading.current = null; }
  }, [applyLayout]);

  useEffect(() => {
    mounted.current = true; void refresh();
    const timer = setInterval(() => {
      if (typeof document === 'undefined' || !document.hidden) void refresh();
    }, 10000);
    const subscription = AppState.addEventListener('change', value => { if (value === 'active') void refresh(); });
    return () => { mounted.current = false; ++sequence.current; clearInterval(timer); subscription.remove(); };
  }, [refresh]);

  const login = async (username: string, password: string) => {
    if (authTransition.current) throw new Error('正在切换登录状态，请稍等');
    authTransition.current=true;
    try {
      // Let every old response install its cookies before issuing a new login.
      if (reading.current) await reading.current;
      await request('/login', { method: 'POST', body: JSON.stringify({ username, password }) });
    } finally { authTransition.current=false; }
    await refresh();
  };
  const mutate = async <T,>(path: string, method: string, payload: unknown = {}): Promise<T> => {
    const actor = current.current;
    if (actor.user?.role !== 'member') throw new ApiError('请先登录', 401);
    const fresh = await request<Session>('/me');
    if (signature(fresh) !== signature(actor)) { await refresh(); throw new ApiError('登录身份已变化，请重新打开此操作', 409); }
    try {
      const result = await request<T>(path, { method, body: JSON.stringify(payload) }, actor.csrf || '');
      if (signature(actor) !== signature(current.current)) throw new ApiError('登录身份已变化，请刷新查看', 409);
      ++sequence.current;
      if (reading.current) await reading.current;
      if (mounted.current) setRefreshing(false);
      return result;
    } catch (failure) {
      if (failure instanceof ApiError && [401, 403, 409].includes(failure.status)) await refresh();
      throw failure;
    }
  };
  const savePreferences = async (patch: Partial<Preferences>) => {
    if (preferenceWriting.current) throw new Error('正在保存显示设置，请稍等');
    preferenceWriting.current=true;
    const actor = signature(current.current);
    try {
      const result = await mutate<Preferences>('/preferences', 'PUT', { ...preferencesRef.current, ...patch });
      if (actor === signature(current.current)) { preferencesRef.current=result; setPreferences(result); }
      await refresh();
    } finally { preferenceWriting.current=false; }
  };
  const logout = async () => {
    if (authTransition.current) throw new Error('正在切换登录状态，请稍等');
    authTransition.current=true;
    try {
      if (reading.current) await reading.current;
      await mutate('/logout', 'POST');
      ++sequence.current; current.current = { user: null }; setSession({ user: null }); setState(null); setPreferences(defaults); layoutRef.current=defaultLayout; setLayout(defaultLayout);
      preferencesRef.current=defaults;
    } finally { authTransition.current=false; }
    await refresh();
  };
  return { user: session.user, identityKey: signature(session), state, preferences, layout, applyLayout, focus, setFocus, loading, refreshing, online, error, notice, setNotice, refresh, login, logout, mutate, savePreferences };
}

const Context = createContext<ReturnType<typeof useHouseholdState> | null>(null);
export function HouseholdProvider({ children }: { children: React.ReactNode }) { return <Context.Provider value={useHouseholdState()}>{children}</Context.Provider>; }
export function useHousehold() { const context = useContext(Context); if (!context) throw new Error('HouseholdProvider is missing'); return context; }
