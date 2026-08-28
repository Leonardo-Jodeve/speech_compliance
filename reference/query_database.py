
from sqlalchemy import create_engine, text
import traceback
import json
import decimal
import datetime

def rows_to_markdown(rows):

    # 转化为 Markdown 表格格式
    headers = list(rows[0]._mapping.keys())
    md_lines = []
    # 表头
    md_lines.append("| " + " | ".join(headers) + " |")
    # 分隔线
    md_lines.append("|" + "|".join(["---"] * len(headers)) + "|")
    # 数据行
    for row in rows:
        row_vals = []
        for key in headers:
            val = row._mapping[key]
            if isinstance(val, decimal.Decimal): val = round(float(val), 2)
            elif isinstance(val, (datetime.date, datetime.datetime)): val = str(val)
            elif val is None: val = "-"
            row_vals.append(str(val))
        md_lines.append("| " + " | ".join(row_vals) + " |")

    markdown_table = "\n".join(md_lines)
    return markdown_table


db_ip = "132.234.6.59"
db_port = "15432"
db_name = "yzdm"
db_username = "yz_ai_agent"
db_password = "***********"


def main(db_ip: str, db_port: str, db_name: str, db_username: str, db_password: str) -> dict:


    # 数据库连接串
    engine = create_engine(
        f"postgresql://{db_username}:{db_password}@{db_ip}:{db_port}/{db_name}"
    )

    try:
        with engine.connect() as connection:
            # 1. 获取元数据
            sql = text(f"""
                select * from sor.dm_eva_feedorder_call_detail
            """)
            result = connection.execute(sql).fetchall()
            result_markdown = rows_to_markdown(result)

            # 组装成功返回的字典
            return {
                "result": "success",
                "message": "元数据获取成功",
                "data": result_markdown
            }

    except Exception as e:
        return {
            "result": "fail",
            "message": "读取数据库元数据时出错，错误堆栈：\n" + str(traceback.format_exc()),
            "data": ""
        }