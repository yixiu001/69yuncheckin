## 2026-07-26 — CI: 升级 GitHub Actions 以移除 Node.js 20 警告

变更摘要
- 升级工作流中使用的 action：
  - `actions/checkout@v2` → `actions/checkout@v4`
  - `actions/setup-python@v2` → `actions/setup-python@v4`
- 目标文件：`.github/workflows/69yuncheckin.yaml`
- 提交信息（建议）：`chore: upgrade actions/checkout and actions/setup-python to @v4 to avoid Node.js 20 deprecation warnings`

为什么要做这次更新
- GitHub 的部分官方 Action 在内部使用的 Node.js 版本已更新或弃用旧版本（如 Node.js 20）。将 action 升级到当前 major 版本可以消除关于被弃用 Node.js 运行时的警告并获得兼容性、性能与安全修复。

影响与风险
- 影响范围：仅 CI 配置文件，运行脚本 `69yun.py` 的流程不变。
- 风险等级：低。多数官方 action 在 major 升级中兼容旧用法，但个别 edge-case 配置或行为差异可能出现。建议合并后观察一次手动触发的运行日志。

验证步骤
1. 在 GitHub 上通过 workflow_dispatch 手动触发 `.github/workflows/69yuncheckin.yaml`。
2. 检查 Actions 日志：
   - 确认 workflow 能成功 checkout、安装 Python、并执行 `python 69yun.py`。
   - 确认不再出现关于“Node.js 20 已弃用”的警告。
3. 如有问题，查看对应 action 的 release notes（Marketplace / GitHub 仓库）寻找迁移建议或已知问题。

如何回滚
- 如果发现不兼容问题，可将 `.github/workflows/69yuncheckin.yaml` 中的 action 引用改回原来的版本（@v2），并提交回滚 commit 或在 PR 中 revert。

相关改动示例（摘录）
```diff
-      - name: Checkout code
-        uses: actions/checkout@v2
+      - name: Checkout code
+        uses: actions/checkout@v4

-      - name: Set up Python
-        uses: actions/setup-python@v2
+      - name: Set up Python
+        uses: actions/setup-python@v4
         with:
           python-version: '3.9'


# 更新内容
系统提示 Warning: Node.js 20 is deprecated. The following actions target Node.js 20 but are being forced to run on Node.js 24: actions/checkout@v2, actions/setup-python@v2.
我把 actions/checkout@v2 → actions/checkout@v4，actions/setup-python@v2 → actions/setup-python@v4

# 项目配置教程

## 1. 点击 Star 和 Fork 这个项目

视频教程：https://youtu.be/HjECaEIH4_s

### 1.1 点击 Star

点个Star支持一下，非常感谢！

### 1.2 Fork 项目

- **步骤**：
    1. 打开该项目的 GitHub 页面。
    2. 在页面右上角，点击 **Fork** 按钮。
    3. 选择你要 Fork 到的 GitHub 账户或组织。

---

## 2. 配置环境变量

### 2.1 在 GitHub 中设置 Secrets（环境变量）

为了让 CI/CD 流程使用敏感信息（如 `BOT_TOKEN`, `CHAT_ID`, `USER1`, `PASS1` 等），我们使用 GitHub 的 **Secrets** 功能存储环境变量，这样可以安全地管理配置。

- **步骤**：
    1. 打开你的 GitHub 仓库页面。
    2. 点击页面右上角的 **Settings** 按钮。
    3. 在左侧菜单栏找到 **Secrets and variables**，点击 **Actions**。
    4. 点击 **New repository secret** 按钮，添加以下 Secrets：
        - `BOT_TOKEN`：你的 Bot Token。
        - `CHAT_ID`：你的 Chat ID。
        - `USER1`, `USER2`, `USER3`（根据需要添加）：第一个、第二个、第三个用户的用户名（如邮件地址）。
        - `PASS1`, `PASS2`, `PASS3`（根据需要添加）：与上述用户对应的密码。

> **注意**：Secrets 一旦设置好后，GitHub Actions 会自动读取它们，无需手动在每次提交时修改代码，但是在工作流中只配置了2个账户，所以需要添加更多账户的话，请手动修改yaml文件。

### 2.2 在 GitHub Actions 中引用环境变量

GitHub Actions 会自动加载你设置在 **Secrets** 中的环境变量，你可以在 `.yaml` 文件中通过 `${{ secrets.<secret_name> }}` 的方式引用这些环境变量。

#### 如果需要添加更多账户请手动修改.github/workflows/69yuncheckin.yaml文件的如下内容

```yaml
jobs:
  build:
    runs-on: ubuntu-latest
    env:
      BOT_TOKEN: ${{ secrets.BOT_TOKEN }}
      CHAT_ID: ${{ secrets.CHAT_ID }}        # 这里设置可以用于多个账户
      USER1: ${{ secrets.USER1 }}            # 用户1
      PASS1: ${{ secrets.PASS1 }}            # 密码1
      USER2: ${{ secrets.USER2 }}            # 用户2
      PASS2: ${{ secrets.PASS2 }}            # 密码2
      # 可以继续扩展更多用户和密码，例如
      USER3: ${{ secrets.USER3 }}            # 用户3
      PASS3: ${{ secrets.PASS3 }}            # 密码3
      USER4: ${{ secrets.USER4 }}            # 用户4
      PASS4: ${{ secrets.PASS4 }}            # 密码4
```

### 2.3 手动运行工作流，后续每天都会自动运行
