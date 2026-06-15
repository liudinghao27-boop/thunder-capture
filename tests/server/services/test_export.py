import io
import csv
from server.services.export import generate_csv, generate_xlsx


def test_generate_csv_with_rows():
    rows = [
        {"id": 1, "platform": "douyin", "user_name": "u1", "text": "hello"},
        {"id": 2, "platform": "douyin", "user_name": "u2", "text": "world"},
    ]
    fields = ["id", "platform", "user_name", "text"]
    output = generate_csv(rows, fields=fields)
    content = "".join(output)
    reader = csv.reader(io.StringIO(content))
    data = list(reader)
    assert len(data) == 3  # header + 2 data rows
    assert data[0][fields.index("user_name")] == "用户昵称"
    assert data[1][fields.index("user_name")] == "u1"
    assert data[2][fields.index("text")] == "world"


def test_generate_xlsx_with_rows():
    rows = [
        {"id": 1, "platform": "douyin", "user_name": "u1", "text": "hello"},
    ]
    fields = ["id", "platform", "user_name", "text"]
    output = generate_xlsx(rows, fields=fields)
    data = output.read()
    assert data.startswith(b"PK")
    assert len(data) > 100
