import numpy as np
import pandas as pd
from matplotlib import pyplot as plt

plot = False

width = 100
num_steps = 1000
# x vals
time = np.arange(0, width, 100 / num_steps)
print('Number of data points:', time.shape[0])
# y vals
price = np.sin(time) + 10

if plot:
    plt.plot(time, price)
    plt.title('Sample Time Series')
    plt.xlabel('Time (min)')
    plt.ylabel('Price')
    plt.show()

zeros = np.zeros(num_steps)
df = pd.DataFrame({'Price': price, 'Pad': zeros})
df.to_csv('sin.csv', index=False)