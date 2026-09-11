def calculate(expression=[]):
    try:
        value = input("请输入表达式：")
        expression.append(value)
        return eval(value)
    except:
        return None


print(calculate())
