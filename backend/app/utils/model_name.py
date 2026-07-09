"""模型名规范化：全项目统一的规范形。

规则（rule）：**所有录入数据库的模型名，一律规范化为 `strip().lower()` 的全小写形。**
不同来源（实跑明细、平台输入各 sheet）对同一模型大小写写法不一（GLM-5.1 / glm-5.1、
Deepseek-v3.2 / deepseek-v3.2、KIMI-K2.5 / kimi-k2.5 …），仅大小写差异；统一小写后即可
作为跨表 join 的规范键，且与实跑明细既有写法一致。

如需展示用的规范大小写，另行在展示层做映射，**存储层始终存小写规范形**。
"""
from __future__ import annotations


def normalize_model_name(raw: object) -> str:
    """把任意来源的模型名规范化为小写规范形。

    - 去首尾空白、折叠内部连续空白为单个空格
    - 全部转小写
    空值返回空字符串。
    """
    if raw is None:
        return ""
    s = " ".join(str(raw).split())  # 去首尾 + 折叠内部空白
    return s.lower()
