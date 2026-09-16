# 足迹地图的本地底图

本资产供后续足迹地图的世界概览使用。仅提供海陆轮廓；不包含用户地点、行政归属判定、地址查找、街道导航或实时地图服务。加入资产不代表地图功能已实现或上线。

## 来源与许可

来源为 Natural Earth 的 1:110m land 图层。官方[使用条款](https://www.naturalearthdata.com/about/terms-of-use/)将网站的矢量/栅格数据置于公共领域，允许修改和分发。本项目保留“Made with Natural Earth”署名及来源，界面实现时同样显示署名。

- [上游仓库](https://github.com/nvkelso/natural-earth-vector)。
- 固定提交：`ca96624a56bd078437bca8184e78163e5039ad19`。
- [固定原始文件](https://raw.githubusercontent.com/nvkelso/natural-earth-vector/ca96624a56bd078437bca8184e78163e5039ad19/geojson/ne_110m_land.geojson)。
- 本地文件：[journey-map-land.geojson](../static/journey-map-land.geojson)。
- 原件原字节保留：138160 bytes，SHA-256 `9e0729ee253ca7d7a5c4ae9395fb1902264c5377c52e224d13dd85010e2835d9`。
- 取得并核验日期：2026-09-16；127 个地物、5143 个坐标点，Polygon/MultiPolygon，有限经纬度及闭环检查通过。

## 渲染与隐私边界

前端从同源静态资源读取此文件，以 SVG 渲染全球概览，再叠加当前成员有权读取的地点投影。底图可以缓存；成员地点响应不得进入公共缓存。没有外站瓦片、地图 SDK、外部字体或后台地理编码请求。不能把细节有限的世界轮廓当作精确城市/街道定位。

经纬度坐标按经度、纬度排列；跨经线的路线和极区需在前端专项处理。缩放/移动不能恢复服务端已经删除或粗化的敏感坐标。底图下载或渲染失败时仍保留地点列表、筛选和编辑入口；不要用空地图宣称无地点。

验收应覆盖：同源请求、无外站请求、海陆轮廓正常、三种地点状态区分、键盘可操作列表、窄屏/主题可读、跨日期变更线不横穿全球的错误连线，以及未授权数据不进入 DOM/响应。数据文件校验本身不代替这些浏览器验收。
