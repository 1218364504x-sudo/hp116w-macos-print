# HP Laser MFP 116w printing on macOS

在 Apple Silicon Mac 上为 HP Laser MFP 116w 保留两条已验证的 CUPS 打印路径：`HP116W_600dpi` 和 `HP116W_1200dpi`。项目处理 WPS Office 导出 PDF 时浅灰、阴影和高亮丢失的问题，并在手动双面打印时保持奇偶页顺序。这里保存的是现有生产链的源码、配置、PPD、Python wheels 和验收记录；本次整理没有改变打印逻辑。原机的完整 Ghostscript 二进制包和带固定网络地址的历史安装包只留在本机，公开仓库不是可直接运行的完整恢复包。

## 支持范围与当前状态

| 项目 | 已确认状态 |
| --- | --- |
| 设备与平台 | HP Laser MFP 116w、macOS CUPS、Apple Silicon；打包的 NumPy wheel 面向 macOS 14 arm64 / CPython 3.9。其他系统组合未验证。 |
| `HP116W_600dpi` | 正式队列，默认 `Normal`、600 dpi、A4；2026-09-28 的 WPS `.docx` 灰度修订已纸面验收并冻结。 |
| `HP116W_1200dpi` | 正式队列，默认 `High`、1200 dpi、A4；2026-09-15 的 WPS A4、真实 1200 dpi、阴影与页序验收通过并冻结。 |
| 系统默认队列 | 验收记录为 `HP116W_600dpi`。两队列在当时均 enabled、accepting、idle。 |
| 手动双面 | 奇数页正常顺序、偶数页逆序已纸面验收。纸张翻面方向仍应按实际进纸方式操作。 |

以上是 [最终生产记录](FINAL_PRODUCTION_STATUS.md) 的快照，不是对其他 macOS 版本、应用或打印机型号的兼容性承诺。600 dpi 的最新 Router/config 哈希见该记录开头；1200 dpi 的纸面结果见 [1200 dpi 验收记录](analysis/wps-docx-halftone-fix/FINAL_1200_PRODUCTION_STATUS.md)。

## 打印链

```text
PDF
  -> hp116w_smart_cups_filter（需要时用 pypdf 选页/排序一次）
  -> hp116w_smart_router（识别队列、分辨率及 PDF 结构）
  -> WPS Selective / Generic 600 / Generic 1200 / Native cgpdftoraster
  -> CUPS Raster
  -> rastertoqpdl（由 Wrapper 调用一次）
  -> CUPS socket 队列 -> HP Laser MFP 116w
```

[Wrapper](analysis/wps-docx-halftone-fix/hp116w-smart-router-dev/hp116w_smart_cups_filter) 接收 CUPS 作业，先用固定的 `pypdf` 运行时处理 `page-ranges`、`page-set` 和正/逆序；无需改页时直接传原 PDF。它删除已处理的页序选项，运行 [Router](analysis/wps-docx-halftone-fix/hp116w-smart-router-dev/hp116w_smart_router)，验证 Raster 后只调用一次系统 `rastertoqpdl`。Router 通过 [生产配置](analysis/wps-docx-halftone-fix/hp116w-smart-router-dev/smart-router-config.json) 校验相关文件哈希，选择 [WPS Dispatcher](analysis/wps-docx-halftone-fix/dev-queue-integration/hp116w_wps_dispatcher.py)、Generic 适配器或原生 `cgpdftoraster`。Filter 不直接访问打印机网络端口。

原生 `cgpdftopdf` 曾重写 WPS PDF 的页尺寸/元数据并造成阴影回归，现已退出生产选页路径。`pypdf` 这一步不栅格化、扁平化、缩放或转换颜色。详见 [生产链说明](analysis/wps-docx-halftone-fix/hp116w-smart-router-dev/README.md)。

## 600 dpi 路径

`HP116W_600dpi` 先尝试高置信度的 `WPS_SELECTIVE_600`。对未命中该分支的 PDF，结构分类器将带 SMask 的矢量文字以及特定 WPS/Quartz ICCBased 文档送至 `GENERIC_HIGHLIGHT_A`；普通 ICCBased 图片密集文档和无法确定结构的文档走 Native。Generic 600 保留经验证的 Highlight A Ghostscript transfer：输入 RGB190、CosineDot 106.17 LPI / 45°、600×600 dpi、1-bit Gray Raster。

最新修复针对 WPS `.docx` 导出的浅灰：WPS Selective 精确识别 `0.9098039` 目标灰，但有些文档使用 `0.9294118`、`0.9568627` 等灰值，导致虽识别为 WPS 却没有目标灰页。600 dpi Router 现在把这类 **WPS 检测通过但无目标灰页** 的作业交给既有 Generic 分类器，使 Generic Highlight A 有机会处理阴影/浅灰。这一条件只作用于 600 dpi；纸面记录确认阴影、页序及奇偶页通过。代码见 [600 dpi 适配器](analysis/wps-docx-halftone-fix/hp116w-smart-router-dev/production-runtime/runtime/hp116w_generic_600.py) 和 [600 dpi 状态](analysis/openprinting-gray-600/FINAL_600_PRODUCTION_STATUS.md)。

## 1200 dpi 路径

`HP116W_1200dpi` 使用独立的 `WPS_SELECTIVE_1200` 和 `GENERIC_RGB235_1200` 分支。Generic 1200 使用 RGB235、CosineDot 106.17 LPI / 45°、1200×1200 dpi、1-bit Gray Raster，**不使用** 600 dpi Highlight A transfer。修复后它向 `cgpdftoraster` 显式传入 PPD 支持的 1200 dpi 质量参数，并校验输出分辨率；Generic 1200 若未得到真实 1200 dpi 会失败，不会降级当作 600 dpi 成功。队列身份可在应用省略质量选项时确定 1200 路由；显式冲突的 600 dpi 选项不会被强制送入 1200 分支。

既有验收记录包括 WPS A4 检测、RGB235 激活、阴影/黑字/版面纸面通过，以及 9500×13617 像素、1188 bytes/line 的真实 1200 dpi Raster。见 [1200 dpi 适配器](analysis/wps-docx-halftone-fix/hp116w-smart-router-dev/production-runtime/runtime/hp116w_generic_1200.py) 和 [1200 dpi 状态](analysis/wps-docx-halftone-fix/FINAL_1200_PRODUCTION_STATUS.md)。

## WPS Office / Quartz PDF 兼容处理

WPS Selective 是先行的高置信度路径。识别条件检查 WPS Office Creator、`.docx` Title、Quartz PDFContext Producer、Letter/A4 页尺寸（1 pt 容差）、ICCBased 和矢量内容。A4 检测曾缺失，现已修复。对 WPS/Quartz 导出的特定 ICCBased 图片密集 PDF，Generic 分类器有窄范围例外；普通 ICCBased 图片密集 PDF 仍走 Native，避免把所有图片文档都强制套用灰度修复。更完整的检测依据见 [WPS 检测说明](analysis/wps-docx-halftone-fix/wps-detector.md) 和 [网点设计](analysis/wps-docx-halftone-fix/selective-halftone-design.md)。

## PPD、队列与手动双面

[600 dpi PPD](analysis/wps-docx-halftone-fix/fixed-queues/HP116W_600dpi.ppd) 与 [1200 dpi PPD](analysis/wps-docx-halftone-fix/fixed-queues/HP116W_1200dpi.ppd) 分别对应两个正式队列；两者都指向共享 Wrapper 和 `rastertoqpdl`。已验证机器上的 PPD 位于 `/private/etc/cups/ppd/`，Filter 位于 `/usr/libexec/cups/filter/`，运行时位于 `/Library/Application Support/HP116W/runtime/`。这几个是 macOS 系统路径，不是某位用户的主目录。打印机网络地址请在本机配置中核对，以下用 `<printer-ip>` 表示。

Wrapper 按先选范围、再选奇偶、最后逆序的顺序处理页面。六页文档的已记录示例：`odd + normal` 为 1、3、5；`even + reverse` 为 6、4、2。已有物理验收覆盖奇数正序、偶数逆序。调用时可使用 CUPS 选项：

```sh
lp -d HP116W_600dpi -o page-set=odd  -o outputorder=normal  document.pdf
lp -d HP116W_600dpi -o page-set=even -o outputorder=reverse document.pdf
```

第二次送纸前按已验证的本机纸张翻面方式操作；本仓库没有通用于所有进纸方向的翻纸图示。

## 文件与运行依赖

| 路径 | 用途 |
| --- | --- |
| [`hp116w-smart-router-dev/`](analysis/wps-docx-halftone-fix/hp116w-smart-router-dev/) | Wrapper、Router、生产配置、PPD 候选和 Ghostscript 运行时哈希记录。带原机网络地址的历史安装器及其清单未公开。 |
| [`production-runtime/runtime/`](analysis/wps-docx-halftone-fix/hp116w-smart-router-dev/production-runtime/runtime/) | Normalizer、600/1200 Generic 适配器和运行配置。原机 Ghostscript 二进制/资源未公开，仍是恢复依赖。 |
| [`600-cups-runtime-fix/wheels/`](analysis/wps-docx-halftone-fix/600-cups-runtime-fix/wheels/) | 已钉住的 NumPy、Pillow、pypdf、typing_extensions wheels；属于恢复依赖。 |
| [`fixed-queues/`](analysis/wps-docx-halftone-fix/fixed-queues/) | 两个正式队列的 PPD 源文件。 |
| [`analyze_spl3_capture.py`](analysis/wps-docx-halftone-fix/print-quality-validation/analyze_spl3_capture.py) | 只读检查 SPL3/QPDL 捕获文件的辅助脚本，不替代纸面验收。 |
| [`openprinting-gray-600/`](analysis/openprinting-gray-600/) | 600 dpi 状态和历史安装材料。 |
| [`FINAL_PRODUCTION_STATUS.md`](FINAL_PRODUCTION_STATUS.md) | 生产状态、验收项目、哈希与清理记录。 |

系统 `cgpdftoraster`、`rastertoqpdl` 和 macOS `/usr/bin/python3` 是已验证主机上的外部依赖，配置及既有状态记录保留其哈希；本仓库没有把它们伪装成通用 macOS 驱动。原机 Ghostscript 10.07.1 二进制包因公开再分发所需的完整来源/许可材料未核实而不上传；它仍留在本地，不影响现有打印链。PDF 回归样本可能含原始打印内容或元数据，也未纳入 GitHub 仓库。

## 安装、部署与恢复

1. 在目标 Apple Silicon Mac 上先确认 CUPS、Python ABI、`cgpdftoraster`、`rastertoqpdl`、兼容的 Ghostscript 运行时、打印机网络连接，以及现有队列和已安装文件的哈希。把当前工作的 Filter、runtime、PPD、队列 URI 与默认队列信息单独备份。目标机的 `<printer-ip>` 必须由使用者核对。
2. 对照 [生产状态记录](FINAL_PRODUCTION_STATUS.md) 核对源码、配置、依赖、两个 PPD 与目标机。原机历史安装器及 manifest 含固定哈希、队列及 URI 校验，未纳入公开仓库；部署新主机需准备与目标版本一致、经核对的安装清单和 Ghostscript 运行时。PPD 只是 Filter 图的一部分，单独注册队列不能完成本项目部署。
3. 当 Filter、runtime 与哈希清单已按目标机一致地部署后，再用对应 PPD 注册 `HP116W_600dpi` 与 `HP116W_1200dpi`，分别设置 Normal/600/A4 与 High/1200/A4，并按需要将 600 队列设为默认。验收记录中的两条队列都使用 CUPS `socket://<printer-ip>:9100` 形式的设备 URI。
4. 恢复现有主机时，优先使用部署前保存的原始文件、PPD 和队列设置；本机保留的历史回滚脚本只针对相应安装脚本生成且版本匹配的备份，未纳入公开仓库。恢复后再核对哈希、队列默认质量/分辨率及页序。

**当前恢复限制：** 本机保留的 `install-production-smart-router.sh` 和公开仓库中的 `install-generic-600.sh` 仍钉住早于 2026-09-28 的 Router/config 哈希；前者主要管理 1200 dpi 队列。它们不能按原样一键重建最新的双队列生产链。为了保存已冻结的打印行为，本次没有改写本机脚本、manifest、固定局域网 URI 或生产配置，也没有执行安装。部署新主机需要先将安装清单、Ghostscript 运行时与实际目标版本核对并更新为一致的签署版本。

## 已知限制

- 纸面验收对应上述特定 macOS/Apple Silicon 主机、打印机和文档；未验证跨机型、跨架构或其他 CUPS/系统版本。
- 高置信度 WPS 识别依赖 PDF 元数据、页尺寸和内容结构；其他 PDF 可能走 Generic 或 Native，不能保证任意导出文件都获得相同的浅灰修复。
- 手动双面自动解决的是页序，纸张翻面仍需人工操作。
- 公开仓库只包含脱敏源码/记录。原机历史脚本/manifest 保留目标机的局域网 URI 及固定依赖哈希，仅存放在本机；README 的示例使用 `<printer-ip>`。
- 回归 PDF/DOCX、spool/capture、厂商参考包和试验输出未上传；对这些样本的复测须使用本机已获准的材料。本次整理没有重新执行物理打印测试。
