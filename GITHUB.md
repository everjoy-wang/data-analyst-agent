# 将本项目推送到你的 GitHub

本地仓库已初始化并完成首次提交（分支 `main`）。你只需在 GitHub 上新建仓库，然后把远程地址加上并推送。

## 1. 在 GitHub 网页上新建仓库

1. 打开 [GitHub New repository](https://github.com/new)
2. **Repository name** 例如：`data-analyst-agent`
3. 选 **Public** 或 **Private**
4. **不要**勾选 “Add a README / .gitignore / license”（本地已有 `README.md`）
5. 点击 **Create repository**

## 2. 在本机添加远程并推送

把下面命令里的 `你的用户名` 和 `仓库名` 换成你的实际值。

**HTTPS（适合配合 Git Credential Manager 或 PAT）：**

```powershell
cd G:\xiangmu\data-analyst-agent
git remote add origin https://github.com/你的用户名/仓库名.git
git push -u origin main
```

**SSH（已配置本机 SSH key 到 GitHub）：**

```powershell
cd G:\xiangmu\data-analyst-agent
git remote add origin git@github.com:你的用户名/仓库名.git
git push -u origin main
```

若提示 `remote origin already exists`，可先执行：

```powershell
git remote remove origin
```

再重新 `git remote add origin ...`。

## 3. 认证说明

- **HTTPS**：GitHub 已不支持账户密码推送，需使用 [Personal Access Token (classic)](https://github.com/settings/tokens) 作为密码，或安装 [Git Credential Manager](https://github.com/git-ecosystem/git-credential-manager)。
- **SSH**：在 [SSH keys](https://github.com/settings/keys) 添加本机公钥后，使用 `git@github.com:...` 地址。

## 4. 后续更新代码

```powershell
cd G:\xiangmu\data-analyst-agent
git add -A
git commit -m "描述你的修改"
git push
```

---

**说明**：“部署到 GitHub”通常指 **代码托管**。若还需要 **在线运行**（公网可访问 API 与前端），需要额外使用 **Railway、Render、Fly.io、Azure** 等平台，并在该平台配置环境变量与构建命令；需要的话可以再说一下你倾向的平台，我可以帮你写对应配置。
