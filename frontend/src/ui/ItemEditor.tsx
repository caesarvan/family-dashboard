import React, { useRef, useState } from 'react';
import { Image, ScrollView, StyleSheet, View } from 'react-native';
import { Button, Checkbox, Dialog, HelperText, IconButton, List, Menu, Portal, SegmentedButtons, Text, TextInput } from 'react-native-paper';
import * as ImagePicker from 'expo-image-picker';
import * as ImageManipulator from 'expo-image-manipulator';
import { ApiError } from '../lib/api';
import { useHousehold } from '../lib/household';
import { CalendarEvent, Entity, ItemKind, ListItem } from '../lib/types';

function cents(value:string) {
  value=value.trim();
  if (!value) return null;
  if (!/^\d{1,10}(\.\d{1,2})?$/.test(value.trim())) throw new Error('金额请填写到分，且不能为负数');
  const [whole,fraction='']=value.split('.'); const result=Number(whole)*100+Number(fraction.padEnd(2,'0'));
  if(result>100000000000) throw new Error('金额超出允许范围'); return result;
}
function localParts(value?:string) {
  const date=value?new Date(value):new Date();
  return {day:new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(date),time:value?new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(date):'19:00'};
}
export default function ItemEditor({kind,item,onDismiss}:{kind:ItemKind;item?:Entity;onDismiss:()=>void}) {
  const {state,mutate,refresh,setNotice}=useHousehold(); const existing=item as ListItem|undefined, event=item as CalendarEvent|undefined;
  const [title,setTitle]=useState(item?.title||''); const [owner,setOwner]=useState(item?.owner||'shared');
  const [quantity,setQuantity]=useState(existing?.quantity||'1 件'); const [budget,setBudget]=useState(existing?.budget==null?'':String(existing.budget/100));
  const [actual,setActual]=useState(existing?.actual==null?'':String(existing.actual/100));
  const [due,setDue]=useState(existing?.due||''); const [note,setNote]=useState(item?.note||'');
  const [done,setDone]=useState(!!existing?.done); const [photos,setPhotos]=useState(existing?.photoIds||[]);
  const [startDay,setStartDay]=useState(localParts(event?.start).day),[startTime,setStartTime]=useState(localParts(event?.start).time);
  const [endDay,setEndDay]=useState(localParts(event?.end).day),[endTime,setEndTime]=useState(event?.end?localParts(event.end).time:'20:00');
  const [allDay,setAllDay]=useState(!!event?.allDay),[location,setLocation]=useState(event?.location||'');
  const sources=(state?.sync?.taskSources||[]).filter(source=>source.writable!==false);
  const primary=state?.sync?.primaryTaskSource?.id||'';
  const [sourceId,setSourceId]=useState(!item&&sources.some(s=>s.id===primary)?primary:''); const [sourceMenu,setSourceMenu]=useState(false);
  const [busy,setBusy]=useState(false),[uploading,setUploading]=useState(false),[error,setError]=useState(''),[uncertain,setUncertain]=useState(false);
  const alive=useRef(true); React.useEffect(()=>()=>{alive.current=false;},[]);
  const label=kind==='events'?'安排':kind==='shopping'?'采购':'待办';
  const common={mode:'outlined' as const,dense:true,disabled:busy||uploading};
  const taskCloud=kind==='tasks'&&!item&&!!sourceId;
  async function save() {
    if(busy||uploading||uncertain)return; setBusy(true);setError('');
    try {
      const payload:Record<string,unknown>={title:title.trim(),owner,note};
      if(!payload.title)throw new Error('先填写名称');
      if(kind==='tasks')Object.assign(payload,{done:taskCloud?false:done,owner:taskCloud?'shared':owner,due,tripId:existing?.tripId||'',...(!item?{sourceId}:{})});
      if(kind==='shopping')Object.assign(payload,{done,quantity,budget:cents(budget),actual:cents(actual),photoIds:photos});
      if(kind==='events') {
        if(!/^\d{4}-\d{2}-\d{2}$/.test(startDay)||!/^\d{4}-\d{2}-\d{2}$/.test(endDay)||(!allDay&&(!/^\d{2}:\d{2}$/.test(startTime)||!/^\d{2}:\d{2}$/.test(endTime))))throw new Error('日期用 YYYY-MM-DD，时间用 HH:mm');
        Object.assign(payload,{start:startDay+'T'+(allDay?'00:00':startTime)+':00+08:00',end:endDay+'T'+(allDay?'00:00':endTime)+':00+08:00',allDay,location,source:event?.source||'手动'});
      }
      if(item)payload.revision=item.revision;
      await mutate('/items/'+kind+(item?'/'+encodeURIComponent(item.id):''),item?'PATCH':'POST',payload);
      await refresh(); if(alive.current){setNotice('已保存'+label);onDismiss();}
    } catch(e) {
      if(!alive.current)return;
      const unknown=e instanceof ApiError&&(e.status===0||e.status>=500);
      setUncertain(unknown);setError(unknown?'暂时无法确认保存结果。请先关闭并刷新清单，核对后再操作，避免重复添加。':e instanceof ApiError&&e.status===409?'这条记录已更新。你的输入仍在，请关闭后重新打开最新记录。':e instanceof Error?e.message:'暂时无法保存');
    } finally {if(alive.current)setBusy(false);}
  }
  async function addPhoto() {
    if(uploading||photos.length>=3)return; setUploading(true);setError('');
    try {
      const picked=await ImagePicker.launchImageLibraryAsync({mediaTypes:['images'],allowsMultipleSelection:false,quality:0.9});
      if(picked.canceled||!alive.current)return;
      const asset=picked.assets[0], ratio=Math.min(1,1600/Math.max(asset.width,asset.height));
      const picture=await ImageManipulator.manipulateAsync(asset.uri,[{resize:{width:Math.max(1,Math.round(asset.width*ratio)),height:Math.max(1,Math.round(asset.height*ratio))}}],{compress:0.8,format:ImageManipulator.SaveFormat.JPEG,base64:true});
      if(!alive.current)return;
      const result=await mutate<{id:string}>('/photos','POST',{dataUrl:'data:image/jpeg;base64,'+picture.base64});
      if(alive.current)setPhotos(values=>[...values,result.id].slice(0,3));
    }catch(e){if(alive.current)setError(e instanceof Error?e.message:'图片暂时无法添加');}
    finally{if(alive.current)setUploading(false);}
  }
  return <Portal><Dialog visible onDismiss={()=>{if(!busy&&!uploading)onDismiss();}} style={styles.dialog}>
    <Dialog.Title>{item?'编辑':'添加'}{label}</Dialog.Title>
    <Dialog.ScrollArea style={styles.scroll}><ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.fields}>
      <TextInput {...common} label={kind==='shopping'?'物品名称':'名称'} value={title} onChangeText={setTitle} maxLength={100} autoFocus />
      {kind==='tasks'&&!item&&!!sources.length&&<Menu visible={sourceMenu} onDismiss={()=>setSourceMenu(false)} anchor={<Button mode="outlined" icon="cloud-outline" onPress={()=>setSourceMenu(true)}>{sourceId?sources.find(s=>s.id===sourceId)?.name:'看板本地待办'}</Button>}><Menu.Item title="看板本地待办" onPress={()=>{setSourceId('');setSourceMenu(false);}}/>{sources.map(s=><Menu.Item key={s.id} title={s.name} onPress={()=>{setSourceId(s.id);setSourceMenu(false);}}/>)}</Menu>}
      {!taskCloud&&<SegmentedButtons value={owner} onValueChange={setOwner} buttons={[{value:'shared',label:'一起'},...(state?.people||[]).map(person=>({value:person.id,label:person.name}))]} />}
      {kind==='shopping'&&<><TextInput {...common} label="数量" value={quantity} onChangeText={setQuantity} maxLength={30}/><TextInput {...common} label="预计总价（元，可选）" value={budget} onChangeText={setBudget} keyboardType="decimal-pad"/><View style={styles.photos}>{photos.map((id,index)=><View key={id}><Image source={{uri:'/api/photos/'+encodeURIComponent(id)}} style={styles.photo}/><IconButton icon="close" accessibilityLabel={'移除第'+(index+1)+'张图片'} size={16} onPress={()=>setPhotos(values=>values.filter(value=>value!==id))}/></View>)}</View><Button mode="outlined" icon="image-plus" disabled={busy||uploading||photos.length>=3} loading={uploading} onPress={addPhoto}>添加参考图片 · {photos.length}/3</Button><Text variant="bodySmall">保存后，参考图片与家庭共享。</Text></>}
      {kind==='events'&&<><TextInput {...common} label="开始日期（YYYY-MM-DD）" value={startDay} onChangeText={setStartDay}/>{!allDay&&<TextInput {...common} label="开始时间（HH:mm）" value={startTime} onChangeText={setStartTime}/>}<TextInput {...common} label={allDay?'结束日期（不包含当天）':'结束日期（YYYY-MM-DD）'} value={endDay} onChangeText={setEndDay}/>{!allDay&&<TextInput {...common} label="结束时间（HH:mm）" value={endTime} onChangeText={setEndTime}/>}<Checkbox.Item label="全天安排" status={allDay?'checked':'unchecked'} onPress={()=>setAllDay(!allDay)}/><TextInput {...common} label="地点（可选）" value={location} onChangeText={setLocation} maxLength={200}/><Text variant="bodySmall">时间使用北京时间</Text></>}
      <List.Accordion title="更多选项" left={props=><List.Icon {...props} icon="tune"/>}>
        <View style={styles.fields}>{kind==='tasks'&&<TextInput {...common} label="截止日期（YYYY-MM-DD，可选）" value={due} onChangeText={setDue}/>}<TextInput {...common} label="备注（可选）" value={note} onChangeText={setNote} multiline maxLength={500}/>{kind!=='events'&&!taskCloud&&<Checkbox.Item label={kind==='shopping'?'已买到':'已完成'} status={done?'checked':'unchecked'} onPress={()=>setDone(!done)}/>} {kind==='shopping'&&<TextInput {...common} label="实际总价（元，可选）" value={actual} onChangeText={setActual} keyboardType="decimal-pad"/>}</View>
      </List.Accordion>
      {!!error&&<HelperText type="error" accessibilityRole="alert">{error}</HelperText>}
    </ScrollView></Dialog.ScrollArea>
    <Dialog.Actions><Button disabled={busy||uploading} onPress={onDismiss}>{uncertain?'关闭并核对':'取消'}</Button><Button mode="contained" disabled={busy||uploading||uncertain||!title.trim()} loading={busy} onPress={save}>保存</Button></Dialog.Actions>
  </Dialog></Portal>;
}
const styles=StyleSheet.create({dialog:{width:'92%',maxWidth:540,alignSelf:'center',maxHeight:'92%',borderRadius:16},scroll:{paddingHorizontal:16},fields:{gap:14,paddingVertical:16},photos:{flexDirection:'row',gap:12,flexWrap:'wrap'},photo:{width:82,height:82,borderRadius:8}});
