# SOLOTRIP-QD v3.1

手机端出行工具。

新增：
- 景点详情「高德」：移动端优先尝试调起高德地图 App；已知坐标时直接进入驾车导航。
- 景点详情「小红书」：尝试调起小红书 App，直接搜索“青岛 + 景点 + 打卡 + 机位 + 攻略”；未成功调起时回退到网页版搜索。
- 时间轴右侧 ↗：同样优先调起高德 App。

说明：
- 高德使用官方 URI API 的 `callnative=1`。
- 小红书使用 `xhsdiscover://search/result` deeplink。部分 App 内置浏览器可能限制外部 App 跳转，Safari/Chrome 通常更稳定。
- 地图、图片和 App 跳转均需联网。
- 直接覆盖 GitHub 仓库根目录，无需构建。
