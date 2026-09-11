"""“成绩统计器”示例提交。"""


def summarize(scores: list[int]) -> tuple[float, int, int]:
    """返回平均分、最高分和最低分。"""
    return sum(scores) / len(scores), max(scores), min(scores)


if __name__ == "__main__":
    values = [int(item) for item in input().split()]
    average, highest, lowest = summarize(values)
    print(f"{average:.2f} {highest} {lowest}")
