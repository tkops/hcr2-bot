import plotext as plt

x = list(range(1, 16))
y1 = [8440, 20496, 25976, 58597, 3398, 4303, 45393, 11569, 53650, 18998, 42036, 40382, 15281, 35843, 15207]
y2 = [14048, 27466, 49353, 5178, 3029, 39371, 58095, 39716, 42090, 56955, 33699, 38631, 20662, 49538, 51049]

plt.plot(x, y1, label="Dataset 1")
plt.plot(x, y2, label="Dataset 2")
plt.title("Line Chart")
plt.xlabel("X")
plt.ylabel("Y")
plt.show(legend=True)  # <== statt legend()

