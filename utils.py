import os
import pandas as pd


def load_uploaded_employees(uploaded_files):
    employees = []

    for file in uploaded_files:

        try:
            df = pd.read_excel(file, header=None)

            value = df.iloc[20, 5]

            if isinstance(value, str):
                value = (
                    value.replace("%", "")
                         .replace(",", ".")
                         .strip()
                )

            percent = float(value)

            if percent <= 1:
                percent *= 100

            percent = round(percent, 2)

            if percent >= 75:
                category = "🟢 75–100"
            elif percent >= 50:
                category = "🟡 50–74"
            elif percent >= 20:
                category = "🟠 20–49"
            else:
                category = "🔴 0–19"

            employees.append({
                "Сотрудник": os.path.splitext(file.name)[0],
                "KPI": percent,
                "Категория": category
            })

        except Exception as e:
            print(file.name, e)

    return pd.DataFrame(employees)
