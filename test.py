import pandas as pd

df = pd.read_csv("boss_jobs.csv")
print(df.head())

df.to_excel("boss_jobs.xlsx",index=False)