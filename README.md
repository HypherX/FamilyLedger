# 家庭账本

在自己的电脑上记家庭开支。把支付宝、微信或银行导出的 CSV、Excel、PDF 放进去，由你配置的模型阅读原文并记账。程序不自行判断哪一笔是开支、退款或划转，只保存模型给出的结果，并按这些结果做明细、分类和加总。

数据留在本机。账单原文会发给你填写的模型接口。

## 模型怎么记账

- 日常消费、花呗或信用卡还款、借呗或贷款还款、红包、缴费、手续费都记为支出，并各自有分类。分类不限于餐饮、交通、日用。
- 还款使用「还款」这一类，不会因为原文写成「不计收支」就被丢掉。
- 提现、余额宝转入转出这类自己账户之间的搬家记为划转，不计入净支出。
- 交易关闭、失败、金额为 0 的占位行不入账。
- 退款从支出里扣掉。净支出等于支出减去退款。

可以在「明细」里改分类或归属的家人。某一批想重来，在「导入」里让模型重读。

## 从源码运行

需要 Python 3.12。

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python desktop.py
```

不想开桌面窗口时：

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8766
```

浏览器打开 <http://127.0.0.1:8766>。

界面有五页：总览、明细、导入、家人、模型。

## 配置模型

复制 `secrets.example.json` 为 `secrets.local.json`，填上接口地址、密钥和模型名。第一次启动会把这些写入本机账本。`secrets.local.json` 不会进入 git。也可以在应用的「模型」页修改，并用「测试连接」确认。

调用时只发送模型名和账单内容，温度等参数全部使用接口默认值。

## 自己打包

在这台 Mac 上：

```bash
pip install -r requirements-build.txt
python tools/build_desktop.py
```

产物在 `dist/`：`FamilyLedger-<版本>-macOS-arm64.zip`，以及同名的 `.sha256` 和 `.json`。包没有签名。可以把这三个文件传到 GitHub Releases。

## 数据放在哪里

| 运行方式 | 数据目录 |
|---|---|
| 源码运行 | 项目里的 `data/` |
| 打包后的 Mac 应用 | `~/Library/Application Support/FamilyLedger/data/` |

也可以用环境变量 `FAMILYLEDGER_DATA` 指定目录。

不要把 `data/` 和 `secrets.local.json` 发给别人，里面有密钥和家庭账单。

## 许可证

[MIT](LICENSE)
