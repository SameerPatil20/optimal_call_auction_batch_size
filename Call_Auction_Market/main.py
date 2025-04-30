# main.py (Simulation loop and analysis)
import random
import numpy as np
import csv
from traders import Trader
from market import MarketCDA, MarketCall

# Parameters (example values from Wah et al. environment)
T = 12000             # trading horizon
qmax = 10             # inventory bound
r_bar = 105.0         # long-run mean of fundamental
kappa = 0.05          # mean-reversion
sigma_s = 1e6         # fundamental shock variance
sigma_PV = 5e6        # private-value variance
lambda_s = 0.004     # slow traders' reentry rate
lambda_f = 0.5        # HFT reentry rate
call_interval = 20

# Initialize traders with private values Θ_i drawn i.i.d. from N(0,σ^2_PV) and sorted
traders = {}
for i in range(1000):
    theta_vals = np.random.normal(0, np.sqrt(sigma_PV), 2*qmax+1)
    theta_vals.sort()
    traders[i] = Trader(id=i, is_fast=False, arrival_rate=lambda_s,
                        qmax=qmax, theta=theta_vals,
                        R_min=0, R_max=250, eta=1.0)
# High-frequency trader
theta_vals = np.random.normal(0, np.sqrt(sigma_PV), 2*qmax+1)
theta_vals.sort()
traders[1000] = Trader(id=1000, is_fast=True, arrival_rate=lambda_f,
                       qmax=qmax, theta=theta_vals,
                       R_min=0, R_max=250, eta=1.0)

# Choose market type: 'CDA' or 'CALL', and batch interval for CALL
market_type = 'CALL'
  # experiment with 100, 500, 1000, etc.
market = MarketCDA() if market_type == 'CDA' else MarketCall(call_interval)

# Prepare CSV writers
tf = open('trades.csv', 'w', newline='')
trade_writer = csv.writer(tf)
trade_writer.writerow(['time','buyer_id','seller_id','price','buyer_pos_before','seller_pos_before'])
bf = open('orderbook_snapshots.csv', 'w', newline='')
book_writer = csv.writer(bf)
book_writer.writerow(['time','market_type','bids','asks'])

# Data buffers for metrics
total_trades = 0
spreads = []
price_series = []
trade_records = []  # store in-memory for surplus computation

# Initialize fundamental series
r = np.zeros(T+1); r[0] = r_bar

for t in range(1, T+1):
    # Fundamental update
    shock = np.random.normal(0, np.sqrt(sigma_s))
    r[t] = max(0, kappa*r_bar + (1-kappa)*r[t-1] + shock)
    # Arrivals
    arrivals = []
    slow_arr = np.random.binomial(1000, lambda_s)
    if slow_arr>0: arrivals += list(np.random.choice(1000, slow_arr, replace=False))
    if random.random() < lambda_f: arrivals.append(1000)
    random.shuffle(arrivals)
    # Snapshot order book
    if isinstance(market, MarketCDA):
        bids = sorted(market.bids, key=lambda x: x[0], reverse=True)
        asks = sorted(market.asks, key=lambda x: x[0])
        if bids and asks: spreads.append(asks[0][0]-bids[0][0])
    else:
        bids = sorted(market.buy_orders, key=lambda x: x[0], reverse=True)
        asks = sorted(market.sell_orders, key=lambda x: x[0])
    book_writer.writerow([t, market_type, bids, asks])
    # Best quotes
    if isinstance(market, MarketCDA):
        best_bid = max([p for p,_ in market.bids], default=None)
        best_ask = min([p for p,_ in market.asks], default=None)
    else:
        best_bid = best_ask = None
    # Process arrivals
    for i in arrivals:
        tr = traders[i]
        # Cancel previous
        if tr.outstanding_order:
            typ, price = tr.outstanding_order
            if isinstance(market, MarketCDA):
                if typ=='buy_limit': market.bids=[(p,j) for (p,j) in market.bids if j!=i]
                else: market.asks=[(p,j) for (p,j) in market.asks if j!=i]
            else:
                if typ=='buy_limit': market.buy_orders=[(p,j) for (p,j) in market.buy_orders if j!=i]
                else: market.sell_orders=[(p,j) for (p,j) in market.sell_orders if j!=i]
            tr.outstanding_order=None
            # tr.stored_order=None
        # Decide
        r_hat=(1-(1-kappa)**(T-t))*r_bar + (1-kappa)**(T-t)*r[t]
        if isinstance(market, MarketCDA):
            temp = tr.decide_order(r_hat, best_bid, best_ask, t)
            if(temp is None):
                continue
            otype, price = temp
            market.time=t
            if otype in ('buy','sell') and market.match_trade(tr, otype, price, traders):
                rec=market.trade_log[-1]
                trade_writer.writerow(rec)
                trade_records.append(rec)
                total_trades+=1; price_series.append(rec[3])
            elif otype.endswith('_limit'):
                market.add_order(tr, otype, price); tr.outstanding_order=(otype,price)
        else:
            temp = tr.decide_order(r_hat, best_bid, best_ask, t)
            # print(t, i, temp)
            if(temp is None):
                continue
            otype,price=temp
            market.add_order(tr, otype, price); tr.outstanding_order=(otype,price)
    # CALL clearing
    if isinstance(market, MarketCall) and t>=market.next_clear:
        market.time=t
        market.clear_market(traders)
        for rec in market.trade_log:
            trade_writer.writerow(rec); trade_records.append(rec)
            total_trades+=1; price_series.append(rec[3])
        market.trade_log.clear(); market.next_clear+=market.interval

# Close CSVs
tf.close(); bf.close()

# Metrics
prices=price_series; diffs=np.diff(prices) if len(prices)>1 else np.array([])
price_vol=np.std(diffs) if diffs.size>0 else 0.0
avg_spread=np.mean(spreads) if spreads else None; ntr=total_trades
# Social surplus
total_surplus=market.social_surplus
# Efficiency
bv,sv=[],[]
for tr in traders.values():
    for q in range(1,qmax+1): bv.append(r_bar+tr.theta[q+qmax])
    for q in range(0,-qmax,-1): sv.append(r_bar+tr.theta[q+qmax])
bv.sort(reverse=True); sv.sort()
opt=sum(b-s for b,s in zip(bv,sv) if b>=s)
eff=total_surplus/opt if opt>0 else None
# Trader utilities
final_r=r[T]; slow_sum=0; hft_sum=0
for _, b, s, p, bq, sq in trade_records:
    buyer = traders[b]
    seller = traders[s]
    tb = buyer.theta[bq+1 + qmax]
    ts = seller.theta[sq + qmax]
    bs = (final_r + tb) - p
    ss = p - (final_r + ts)
    if buyer.is_fast:
        hft_sum += bs
    else:
        slow_sum += bs
    if seller.is_fast:
        hft_sum += ss
    else:
        slow_sum += ss
# Print
print(f"Simulation complete: market={market_type}, batch_interval={call_interval}")
print(f"Total trades: {ntr}")
print(f"Price volatility: {price_vol:.4f}")
if avg_spread is not None: print(f"Average spread: {avg_spread:.4f}")
print(f"Efficiency (social/optimum): {eff:.4f}" if eff else "No eff data")
print(f"Total social surplus: {total_surplus:.2f}")
print(f"Slow traders total surplus: {slow_sum:.2f}")
print(f"HFT profit: {hft_sum:.2f}")
