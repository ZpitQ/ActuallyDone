"""自测。在仓库根跑 `python3 -m unittest`。

做成包是为了让**不带任何参数**的 `python3 -m unittest` 就能发现这些用例：
没有 __init__.py 时它会安静地报「Ran 0 tests」，而「一个用例都没跑」
和「全部通过」在终端里长得太像了。
"""
