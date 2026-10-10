"""A 分工的内部实现包。

命名空间的用意：``src/b2_core/`` 是与 B 共用的包，但本项目的文件主人约定里
A 只拥有 ``src/b2_core/model.py`` 和 ``src/b2_core/prompts/``。为了避免和 B 的
``contracts.py`` / ``memory.py`` / ``turn.py`` / ``store.py`` / ``__init__.py``
抢文件名，A 自己的实现细节集中放在这个 ``a_impl`` 子包里。

对外入口仍然是 ``src/b2_core/model.py``：B 只需要 ``from b2_core.model import
ModelEngine, MockEngine``，不需要知道本子包的存在。
"""