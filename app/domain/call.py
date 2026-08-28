"""
CallRecord 领域模型（手册 #8）与从样例 Excel 构造的工具函数。

强制工程要求（手册 #7）：
- 所有业务标识符字段（latn_id / activity_id / order_id / act_scene_id / creator /
  seat_id / object_id / main_acc_nbr / host_call_nbr / guest_called_nbr / p_day）统一按字符串处理；
- 禁止 int(float(...)) 或 float(row[...]) 造成精度损失。
"""
from __future__ import annotations

import datetime as _dt
import hashlib
from dataclasses import dataclass, field

# Excel 中 order_id 等超长数值常以 float 形式读入（可能带科学计数法精度丢失），
# 本模块提供 from_excel_row 用于测试；生产环境一律走数据库 CAST AS TEXT（见 call_database_adapter）。
# 注意：Excel 中 float 已丢失精度，因此 from_excel_row 仅用于演示/测试，生产必须用数据库 CAST。


def _excel_int_to_str(value: object) -> str | None:
    """把 Excel 读出的数值/科学计数法安全转为字符串。

    对 float 采用 repr 恢复原始展示形式（如 1.77734773447953e+39），
    对 int 直接转 str。此转换仍受 Excel 浮点精度限制，仅用于测试/演示。
    """
    if value is None:
        return None
    if isinstance(value, float):
        # 若为整数值的浮点（如 90131206.0）则去掉小数
        if value.is_integer():
            return str(int(value))
        return repr(value)
    if isinstance(value, int):
        return str(value)
    return str(value)


def _num_to_int(value: object) -> int | None:
    """将 call_time / answertime 等数值字段转 int。"""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass
class CallRecord:
    """一期统一领域对象（手册 #8）。"""

    source_call_key: str

    latn_id: str | None = None
    activity_id: str | None = None
    order_id: str | None = None

    opr_pos_code: str | None = None
    opr_pos_name: str | None = None

    scene_id: str = ""
    scene_name: str = ""

    creator: str | None = None

    seat_id: str | None = None
    seat_name: str | None = None

    feedback_result: str | None = None

    object_id: str | None = None
    main_acc_nbr: str | None = None

    host_call_nbr: str | None = None
    guest_called_nbr: str | None = None

    start_time: _dt.datetime | None = None
    end_time: _dt.datetime | None = None

    talk_seconds: int = 0
    call_result: str = ""

    recording_url: str | None = None

    call_source: str | None = None
    call_type: str | None = None

    two_confirm: str | None = None
    terminal_type: str | None = None

    partition_day: str | None = None
    answer_time: int | None = None

    # ---- 派生方法 ----

    def is_qualifiable(self, min_talk_seconds: int = 15) -> bool:
        """是否具备进入质检的资格（手册 #10）：
        call_result = '接通' AND file_url 非空 AND call_time >= min_talk_seconds。
        """
        if self.call_result != "接通":
            return False
        if not self.recording_url or not str(self.recording_url).strip():
            return False
        if self.talk_seconds < min_talk_seconds:
            return False
        return True

    def scene_id_for_log(self) -> str:
        return self.scene_id or "-"

    def masked_phone(self) -> str:
        """脱敏手机号，用于日志（手册 #48）。"""
        phones = [self.host_call_nbr, self.guest_called_nbr, self.main_acc_nbr]
        out = []
        for p in phones:
            if not p:
                continue
            p = str(p)
            if len(p) >= 7:
                out.append(p[:3] + "****" + p[-4:])
            else:
                out.append("***")
        return ",".join(out) if out else "-"


def build_source_call_key(
    order_id: str | None,
    start_time: _dt.datetime | None,
    host_call_nbr: str | None,
    guest_called_nbr: str | None,
) -> str:
    """根据稳定业务字段生成通话唯一键（手册 #13）。"""
    raw = "|".join([
        str(order_id or ""),
        start_time.isoformat() if start_time else "",
        str(host_call_nbr or ""),
        str(guest_called_nbr or ""),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def from_excel_row(
    header: list[str],
    row: list[object],
    min_talk_seconds: int = 15,
) -> CallRecord:
    """从样例 Excel 行构造 CallRecord（仅用于测试/演示/调试）。

    注意：Excel 中 order_id 等超长 ID 以浮点存储，已存在精度损失；
    生产数据必须通过数据库查询（CAST AS TEXT）获取，严禁用本函数替代。
    """
    idx = {h: i for i, h in enumerate(header)}
    get = lambda name: row[idx[name]] if name in idx and idx[name] < len(row) else None

    start_time = get("start_date")
    if isinstance(start_time, str):
        try:
            start_time = _dt.datetime.fromisoformat(start_time)
        except ValueError:
            start_time = None

    order_id = _excel_int_to_str(get("order_id"))
    host = _excel_int_to_str(get("host_call_nbr"))
    guest = _excel_int_to_str(get("guest_called_nbr"))

    return CallRecord(
        source_call_key=build_source_call_key(order_id, start_time, host, guest),
        latn_id=_excel_int_to_str(get("latn_id")),
        activity_id=_excel_int_to_str(get("activity_id")),
        order_id=order_id,
        opr_pos_code=_excel_int_to_str(get("opr_pos_code")),
        opr_pos_name=str(get("opr_pos_name")) if get("opr_pos_name") is not None else None,
        scene_id=_excel_int_to_str(get("act_scene_id")) or "",
        scene_name=str(get("act_scene_name")) if get("act_scene_name") is not None else "",
        creator=_excel_int_to_str(get("creator")),
        seat_id=_excel_int_to_str(get("seat_id")),
        seat_name=str(get("seat_name")) if get("seat_name") is not None else None,
        feedback_result=_excel_int_to_str(get("feedback_result")),
        object_id=_excel_int_to_str(get("object_id")),
        main_acc_nbr=_excel_int_to_str(get("main_acc_nbr")),
        host_call_nbr=host,
        guest_called_nbr=guest,
        start_time=start_time,
        end_time=get("end_time"),
        talk_seconds=_num_to_int(get("call_time")) or 0,
        call_result=str(get("call_result")) if get("call_result") is not None else "",
        recording_url=str(get("file_url")) if get("file_url") is not None else None,
        call_source=_excel_int_to_str(get("call_source")),
        call_type=_excel_int_to_str(get("call_type")),
        two_confirm=_excel_int_to_str(get("twoconfir")),
        terminal_type=_excel_int_to_str(get("terminal_type")),
        partition_day=_excel_int_to_str(get("p_day")),
        answer_time=_num_to_int(get("answertime")),
    )