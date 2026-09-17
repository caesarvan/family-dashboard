import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { AppState } from 'react-native';
import { ApiError, request } from './api';
import { acceptHomeLayout } from './homeLayout';
import { acceptPreferences, readPreferences, readPreferencePayload, PreferenceFence, PreferenceDiscarded, PreferenceError, PreferenceRejected, checkedPreferenceWrite, preferenceRequest, type PreferenceChanges, type PreferenceSession } from './preferences';
import { FamilyState, HomeLayout, Member, Preferences } from './types';

type Session = { user: Member | null; csrf?: string | null };
const signature = (session: Session) => JSON.stringify([session.user?.role, session.user?.householdId, session.user?.id, session.user?.auth_version, session.csrf]);
const defaults: Preferences = { theme: 'forest', colorMode: 'light', density: 'comfortable', homeView: 'today', revision: 0 };
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
  const [preferencesUncertain, setPreferencesUncertain] = useState(false), [preferencesBusy, setPreferencesBusy] = useState(false);
  const current = useRef<Session>({ user: null });
  const sequence = useRef(0);
  const mounted = useRef(true);
  const reading = useRef<Promise<void> | null>(null);
  const authTransition = useRef(false);
  const preferenceWriting = useRef(false);
  const preferencesRef = useRef(defaults);
  const preferenceUnknown = useRef<string | null>(null), preferenceController = useRef<AbortController | null>(null), preferenceEpoch = useRef(0);
  const foreground = useRef(AppState.currentState !== 'background' && AppState.currentState !== 'inactive');
  const resetPreferences = () => { preferencesRef.current=defaults; setPreferences(defaults); preferenceUnknown.current=null; setPreferencesUncertain(false); ++preferenceEpoch.current; preferenceController.current?.abort(); };
  const applyPreferences = useCallback((next: Preferences, expectedIdentity: string): boolean => {
    if (!mounted.current || current.current.user?.role !== 'member') return false;
    const accepted=acceptPreferences(preferencesRef.current,next,expectedIdentity,signature(current.current));
    if (!accepted) return false;
    preferencesRef.current=accepted; setPreferences(accepted); return true;
  }, []);
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
        if (changed) { setState(null); resetPreferences(); layoutRef.current=defaultLayout; setLayout(defaultLayout); setFocus(next.user?.id || ''); }
        current.current = next; setSession(next);
        if (!next.user || next.user.role !== 'member') { setState(null); setError(''); setOnline(true); return; }
        const appearanceEpoch=preferenceEpoch.current;
        const [snapshot, prefs, cards] = await Promise.all([
          request<FamilyState>('/state'), request<Preferences>('/preferences'), request<HomeLayout>('/dashboard-layout'),
        ]);
        const after=await request<Session>('/me');
        if (!mounted.current || ticket !== sequence.current || signature(next) !== signature(current.current)) return;
        if (signature(after)!==signature(next)) { current.current=after; setSession(after); setState(null); resetPreferences(); layoutRef.current=defaultLayout; setLayout(defaultLayout); setOnline(false); setError('身份已变化，请重新读取家庭数据。'); return; }
        if (appearanceEpoch!==preferenceEpoch.current || !foreground.current || typeof document !== 'undefined' && document.hidden || typeof navigator !== 'undefined' && navigator.onLine===false) return;
        setState(snapshot); applyPreferences(readPreferences(prefs), signature(next)); applyLayout(cards, signature(next));
        setFocus(value => snapshot.people.some(person => person.id === value) ? value : next.user!.id);
        setError(''); setOnline(true);
      } catch (failure) {
        if (!mounted.current || ticket !== sequence.current) return;
        if (failure instanceof ApiError && [401, 403].includes(failure.status)) {
          current.current = { user: null }; setSession({ user: null }); setState(null); resetPreferences(); layoutRef.current=defaultLayout; setLayout(defaultLayout);
        }
        setOnline(false); setError(failure instanceof Error ? failure.message : '暂时无法读取家庭数据');
      } finally { if (mounted.current && ticket === sequence.current) { setLoading(false); setRefreshing(false); } }
    })();
    reading.current = job;
    try { await job; } finally { if (reading.current === job) reading.current = null; }
  }, [applyLayout, applyPreferences]);

  useEffect(() => {
    mounted.current = true; void refresh();
    const timer = setInterval(() => {
      if (typeof document === 'undefined' || !document.hidden) void refresh();
    }, 10000);
    const suspend=()=>{ ++preferenceEpoch.current; preferenceController.current?.abort(); };
    const visibility=()=>{ if(document.hidden) suspend(); else void refresh(); };
    const offline=()=>suspend();
    const subscription = AppState.addEventListener('change', value => { foreground.current=value==='active'; if (foreground.current) void refresh(); else suspend(); });
    if(typeof document!=='undefined')document.addEventListener('visibilitychange',visibility);
    if(typeof window!=='undefined')window.addEventListener('offline',offline);
    return () => { mounted.current = false; ++sequence.current; suspend(); clearInterval(timer); subscription.remove();
      if(typeof document!=='undefined')document.removeEventListener('visibilitychange',visibility);
      if(typeof window!=='undefined')window.removeEventListener('offline',offline); };
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
  const preferenceLive = (actor: string, epoch: number) => mounted.current && !authTransition.current && current.current.user?.role==='member'
    && actor===signature(current.current) && epoch===preferenceEpoch.current && foreground.current
    && (typeof document==='undefined'||!document.hidden) && (typeof navigator==='undefined'||navigator.onLine!==false);
  const preferenceJob = async (patch?: PreferenceChanges) => {
    if (preferenceWriting.current) throw new Error('正在核对显示设置，请稍等');
    const actor=signature(current.current), epoch=preferenceEpoch.current;
    if(!preferenceLive(actor,epoch))throw new Error('请联网并返回前台后核对显示设置');
    if(patch && preferenceUnknown.current===actor)throw new Error('先前显示设置的保存结果不确定，请先点击“核对显示设置”。');
    const payload=patch ? readPreferencePayload({revision:preferencesRef.current.revision,changes:patch}) : undefined;
    preferenceWriting.current=true; setPreferencesBusy(true);
    const controller=new AbortController(); preferenceController.current=controller;
    const fence=new PreferenceFence(actor);
    const guard=<T,>(operation:(csrf:string)=>Promise<T>)=>fence.run(async()=>await preferenceRequest('/me',controller.signal) as PreferenceSession,operation,()=>preferenceLive(actor,epoch));
    try {
      const result=payload ? await checkedPreferenceWrite<Preferences>(operation=>guard(operation),async csrf=>{
        preferenceUnknown.current=actor; setPreferencesUncertain(true);
        return readPreferences(await preferenceRequest('/preferences',controller.signal,payload,csrf));
      }) : readPreferences(await guard(()=>preferenceRequest('/preferences',controller.signal)));
      if(!preferenceLive(actor,epoch)||!applyPreferences(result,actor))throw new PreferenceDiscarded();
      preferenceUnknown.current=null; setPreferencesUncertain(false);
      if(!payload)setNotice('已读取当前显示设置。请核对显示范围；这不能确认刚才请求的执行结果，需要修改时请重新选择。');
    } catch (failure) {
      if(actor===signature(current.current)&&mounted.current) {
        if(failure instanceof PreferenceRejected) { preferenceUnknown.current=null; setPreferencesUncertain(false); }
        const uncertain=preferenceUnknown.current===actor;
        setNotice(uncertain?'显示设置的保存结果不确定。请点击“核对显示设置”，不会自动重复保存。':failure instanceof Error?failure.message:'暂时无法核对显示设置');
        if(failure instanceof PreferenceDiscarded&&failure.message==='identity'||failure instanceof PreferenceError&&[401,403,409].includes(failure.status))void refresh();
      }
      throw failure;
    } finally {
      if(preferenceController.current===controller) { preferenceController.current=null; preferenceWriting.current=false; if(mounted.current)setPreferencesBusy(false); }
    }
  };
  const savePreferences = (patch: PreferenceChanges) => preferenceJob(patch);
  const checkPreferences = () => preferenceJob();
  const logout = async () => {
    if (authTransition.current) throw new Error('正在切换登录状态，请稍等');
    authTransition.current=true;
    try {
      if (reading.current) await reading.current;
      await mutate('/logout', 'POST');
      ++sequence.current; current.current = { user: null }; setSession({ user: null }); setState(null); resetPreferences(); layoutRef.current=defaultLayout; setLayout(defaultLayout);
      preferencesRef.current=defaults;
    } finally { authTransition.current=false; }
    await refresh();
  };
  return { user: session.user, identityKey: signature(session), state, preferences, applyPreferences, preferencesUncertain, preferencesBusy, checkPreferences, layout, applyLayout, focus, setFocus, loading, refreshing, online, error, notice, setNotice, refresh, login, logout, mutate, savePreferences };
}

const Context = createContext<ReturnType<typeof useHouseholdState> | null>(null);
export function HouseholdProvider({ children }: { children: React.ReactNode }) { return <Context.Provider value={useHouseholdState()}>{children}</Context.Provider>; }
export function useHousehold() { const context = useContext(Context); if (!context) throw new Error('HouseholdProvider is missing'); return context; }
