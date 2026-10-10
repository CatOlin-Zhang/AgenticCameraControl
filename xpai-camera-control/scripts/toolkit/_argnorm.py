"""toolkit 入参类型自愈：数字形态的字符串字段统一转为 str。

凭据类字段（密码/SN 等）若以 JSON number 形态传入并写入 YAML 配置，
下次加载后仍为 int，导致按值匹配（int != str）失效、凭据处理异常。
归一化放在 toolkit 各公开函数入口（而非 mcp_server 层），
保证任何调用通道（MCP / 脚本 / 直接 import）行为一致。

注意：tool schema 已将这些字段声明为 string（契约上不接受数字）；
本函数是防御层，覆盖不做 schema 校验的宿主与脚本直调通道，
而非鼓励数字输入。
"""


def coerce_str(value):
    """int / 整值 float 转为 str；None、bool 与其他类型原样返回。

    None 必须原样保留：部分函数以 None 表示"未提供"（如 connect_device
    的 password=None 走缓存/云端授权路径），转成 "None" 会破坏语义；
    bool 是 int 的子类，须显式排除。
    """
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return value
