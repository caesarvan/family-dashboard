import React, { useEffect, useState } from 'react';
import { Platform, View } from 'react-native';
import { Button, Text } from 'react-native-paper';
import { SelectionRow } from '../ui/SelectionRow';
import { terminalImport } from '../lib/photos';
import { LocalPhotoUpload, localSlotMessage, localUploadError, pickLocalPhotos } from '../lib/localPhotoUpload';

export default function LocalPhotoImportPanel({ controller, disabled = false }: { controller: LocalPhotoUpload; disabled?: boolean }) {
  const [view, setView] = useState(controller.view), [consent, setConsent] = useState(false), [pickerError, setPickerError] = useState('');
  useEffect(() => { setView(controller.view); return controller.subscribe(() => setView(controller.view)); }, [controller]);
  const terminal = !!view.detail && terminalImport(view.detail.import.state);
  const stopped = disabled || view.busy || view.unavailable;
  const canChoose = !view.needsCheck && (!view.detail || view.detail.upload?.canUpload);
  function choose() {
    setPickerError('');
    // Open in the user gesture. The page-owned controller survives picker blur;
    // selection is hashed only inside a fresh /me fence after returning.
    void pickLocalPhotos().then(files => controller.select(files)).catch(error => setPickerError(localUploadError(error)));
  }
  return <View style={{ gap: 12 }}>
    <Text variant="bodyMedium">从手机或电脑选择 1～10 张照片，无需连接 Google。每张不超过 8 MiB、2000 万像素，仅支持 JPEG、PNG、WebP 静态照片。</Text>
    <Text variant="bodySmall">只上传本次选择，生成展示副本后再由你确认私密保存。不会同步设备图库或备份原图；暂不支持 HEIC、本地视频和动图。</Text>
    {Platform.OS !== 'web' ? <Text>请使用手机或电脑浏览器选择设备照片。</Text> : <Button mode="outlined" accessibilityLabel={view.detail ? '重新选择原文件' : '从设备选择照片'} disabled={stopped || !canChoose} onPress={choose}>{view.detail ? '重新选择原文件' : '从设备选择照片'}</Button>}
    {view.selected.map(file => <Text key={file.clientFileId} variant="bodySmall">{file.filename} · {(file.bytes / 1024 / 1024).toFixed(2)} MiB{view.detail?.upload?.files.find(row => row.clientFileId === file.clientFileId) ? ' · ' + localSlotMessage(view.detail.upload.files.find(row => row.clientFileId === file.clientFileId)!) : ''}</Text>)}
    {!!view.uploading && <Text accessibilityLiveRegion="polite">正在上传：{view.uploading}</Text>}
    {!!(pickerError || view.message) && <Text accessibilityRole="alert">{pickerError || view.message}</Text>}
    {view.needsCheck && !view.unavailable ? <Button mode="contained" disabled={stopped} onPress={() => void controller.check()}>核对本次上传</Button> : !terminal && (!view.detail || view.detail.upload?.canUpload) ? <>
      <SelectionRow label="允许临时处理本次设备照片，供我预览确认；未保存内容最迟 24 小时后清理。" checked={consent} disabled={stopped} onPress={() => setConsent(value => !value)} />
      <Button mode="contained" disabled={stopped || !consent || !view.selected.length} onPress={() => void controller.upload()}>{view.detail ? '继续上传剩余照片' : '上传并生成预览'}</Button>
      {!!view.detail && <><Text variant="bodySmall">没有原文件时，可跳过剩余照片，只核对已成功的预览。</Text><Button disabled={stopped} onPress={() => void controller.finish()}>结束本批并核对成功项</Button></>}
    </> : !terminal && !!view.detail && <Button disabled={stopped} onPress={() => void controller.check()}>查看本批预览</Button>}
    {terminal && <Button disabled={view.busy || disabled} onPress={() => { controller.reset(); setConsent(false); }}>选择下一批照片</Button>}
  </View>;
}
