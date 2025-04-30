# traders.py
import random

class Trader:
    def __init__(self, id, is_fast, arrival_rate, qmax, theta, R_min, R_max, eta):
        self.id = id
        self.is_fast = is_fast    # HFT or slow
        self.arrival_rate = arrival_rate
        self.qmax = qmax
        self.theta = theta        # size 2*qmax+1, sorted private values
        self.R_min = R_min
        self.R_max = R_max
        self.eta = eta
        self.position = 0         # current net holdings
        self.outstanding_order = None
    def reset(self):
        self.position = 0
        self.outstanding_order = None

    def decide_order(self, r_hat, best_bid, best_ask):
        # Prevent exceeding inventory bounds
        if self.position >= self.qmax:
            side = "sell"
        elif self.position <= -self.qmax:
            side = "buy"
        else:
            side = "buy" if random.random() < 0.5 else "sell"

        # Valuation components
        if side == "buy":
            theta_val = self.theta[self.position+1 + self.qmax]
            val = r_hat + theta_val
        else:
            theta_val = self.theta[self.position + self.qmax]
            val = r_hat + theta_val

        # Draw a shaded limit price
        if side == "buy":
            low = r_hat + self.theta[self.position+1 + self.qmax] - self.R_max
            high = r_hat + self.theta[self.position+1 + self.qmax] - self.R_min
        else:
            low = r_hat + self.theta[self.position + self.qmax] + self.R_min
            high = r_hat + self.theta[self.position + self.qmax] + self.R_max
        if low > high:
            low, high = high, low
        limit_price = random.uniform(low, high)

        # Threshold execution: if current quote gives ≥η of the desired surplus
        if side == "buy" and best_ask is not None:
            surplus_limit = val - limit_price
            surplus_quote = val - best_ask
            if surplus_limit > 0 and surplus_quote >= self.eta*surplus_limit:
                return ("buy", best_ask)
        if side == "sell" and best_bid is not None:
            surplus_limit = limit_price - val
            surplus_quote = best_bid - val
            if surplus_limit > 0 and surplus_quote >= self.eta*surplus_limit:
                return ("sell", best_bid)

        # Otherwise, place limit order
        return (f"{side}_limit", limit_price)

