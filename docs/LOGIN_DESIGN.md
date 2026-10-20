# 登录页设计与动效

## 方向

暗色空间与明亮表单并置；自建 Three.js 玻璃雕塑、轨道、卫星与粒子，Motion 分层入场，鼠标视差、按钮聚光、密码显示、等待与成功反馈。全部几何体、环境光与粒子在本地生成，不需要外部模型、字体或图片服务。

设计参考：
- [Awwwards / Noomo 3D Portal](https://www.awwwards.com/inspiration/3d-portal-noomo-valentime)：玻璃材质与空间层次。
- [Codrops / Glass Effect](https://tympanus.net/Tutorials/GlassEffect/)：光线、透明感与实体空间。
- [Motion / reduced motion](https://motion.dev/docs/react-use-reduced-motion)：尊重系统减少动态效果偏好。

参考用于视觉方向，没有复制站点素材。当前抽象雕塑是登录页视觉资产，不能视作已完成的弗洛洛 Q 版角色 Logo；角色 Logo 仍待独立制作。

## 运行边界

3D 模块按需加载；像素比受限，绘制节流为最多30帧/秒；后台页面停止绘制。提供暂停背景动效按钮；系统减少动态效果模式禁用连续运动。组件卸载释放 GPU 几何、材质、环境贴图与上下文。WebGL 不可用时使用 CSS 图形降级，登录表单和真实认证继续工作。

登录成功后重新加载当前用户，清除其他用户数据缓存；服务端认证、CSRF 和权限边界不受动画影响。动画不代替身份验证，也不显示虚构业务统计。

## 验证入口

前端 `npm run typecheck`、`npm run build`。
浏览器自动化见 `scripts/testing/e2e/login.spec.ts`，覆盖真实登录/登出、部门保存与刷新、权限页面、WebGL 场景、暂停、密码显示、移动端、减少动态效果及无 WebGL 降级。
