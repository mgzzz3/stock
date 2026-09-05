"""Read-only research of archived B1 pools; never changes production strategy."""
from pathlib import Path
import json
import sqlite3
from unittest.mock import patch
import numpy as np
import pandas as pd
from strategy import zb1

ROOT = Path(__file__).resolve().parents[1]
ASOF = "20260904"
START = "20260610"
RNG = np.random.default_rng(20260904)


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [clean(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return round(float(value), 5) if np.isfinite(value) else None
    return value


def block_ci(values, repetitions=1500):
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    n = len(values)
    if n < 10:
        return [None, None]
    starts = RNG.integers(0, n, size=(repetitions, (n + 4) // 5))
    ix = ((starts[:, :, None] + np.arange(5)) % n).reshape(repetitions, -1)[:, :n]
    return (np.quantile(values[ix].mean(axis=1), [.025, .975]) * 100).tolist()


print("Loading archived pools and prices", flush=True)
pool_frames, pred_frames = [], []
for path in sorted((ROOT / "data/signals").glob("b1_*.csv")):
    date = path.stem[-8:]
    if not START <= date <= ASOF:
        continue
    f = pd.read_csv(path, dtype={"ts_code": str})
    f["trade_date"] = date
    pool_frames.append(f)
    prediction = ROOT / "data/predictions" / f"next_day_{date}.csv"
    if prediction.exists():
        p = pd.read_csv(prediction, dtype={"ts_code": str})
        p["trade_date"] = date
        p["prediction_rank"] = np.arange(1, len(p) + 1)
        pred_frames.append(p[["ts_code", "trade_date", "prob_up", "prediction_rank"]])
pool = pd.concat(pool_frames, ignore_index=True).drop_duplicates(["trade_date", "ts_code"])
pred = pd.concat(pred_frames, ignore_index=True).drop_duplicates(["trade_date", "ts_code"])
with sqlite3.connect(f"file:{ROOT / 'data/stock.db'}?mode=ro", uri=True) as conn:
    daily = pd.read_sql_query("SELECT ts_code,trade_date,open,high,low,close,pre_close,pct_chg,vol,amount FROM daily WHERE trade_date BETWEEN '20260201' AND ? ORDER BY ts_code,trade_date", conn, params=[ASOF])
    sectors = pd.read_sql_query("SELECT trade_date,industry,rank AS sector_rank,score AS sector_score,return_5d AS sector_return5,breadth AS sector_breadth,relative_strength AS sector_relative FROM sector_ranking_history WHERE trade_date BETWEEN ? AND ?",conn,params=[START,ASOF])
    financials = pd.read_sql_query("SELECT ts_code,report_date,announcement_date,roe,debt_to_assets,ocf_per_share FROM fundamental_annual WHERE announcement_date <= ? AND substr(report_date,5,4)='1231'",conn,params=[ASOF])
dates = sorted(daily.trade_date.unique())
di = {d: i for i, d in enumerate(dates)}
daily["idx"] = daily.trade_date.map(di)
g = daily.groupby("ts_code", sort=False)
daily["adj_close"] = (1 + daily.pct_chg.fillna(0) / 100).groupby(daily.ts_code).cumprod()
daily["adj_open"] = daily.adj_close * daily.open / daily.close
g = daily.groupby("ts_code", sort=False)
for h in [1, 3, 5, 10, 20, 60]:
    daily[f"mom{h}"] = daily.adj_close / g.adj_close.shift(h) - 1
for h in [5, 20, 60]:
    daily[f"ma{h}_adj"] = g.adj_close.transform(lambda s: s.rolling(h).mean())
daily["ma20_slope"] = daily.ma20_adj / daily.groupby("ts_code", sort=False).ma20_adj.shift(5) - 1
daily["dist_ma20"] = daily.adj_close / daily.ma20_adj - 1
daily["volatility10"] = g.mom1.transform(lambda s: s.rolling(10).std())
daily["atr14_pct"] = pd.concat([(daily.high-daily.low)/daily.pre_close, (daily.high/daily.pre_close-1).abs(), (daily.low/daily.pre_close-1).abs()], axis=1).max(axis=1).groupby(daily.ts_code).transform(lambda s:s.rolling(14).mean())
daily["close_position"] = ((daily.close-daily.low)/(daily.high-daily.low)).fillna(.5)
daily["amount20"] = g.amount.transform(lambda s:s.rolling(20).mean())
daily["market20"] = daily.groupby("trade_date").mom20.transform("median")
daily["market1"] = daily.groupby("trade_date").mom1.transform("median")
daily["relative20"] = daily.mom20-daily.market20
daily["next_gap"] = g.open.shift(-1) / g.pre_close.shift(-1) - 1
next_open = g.adj_open.shift(-1)
for h in [1, 3, 5, 10, 20]:
    valid = g.idx.shift(-1).eq(daily.idx+1) & g.idx.shift(-h).eq(daily.idx+h) & g.vol.shift(-1).gt(0)
    daily[f"fwd{h}"] = (g.adj_close.shift(-h)/next_open-1).where(valid)
    daily[f"market_fwd{h}"] = daily.groupby("trade_date")[f"fwd{h}"].transform("mean")
features = ["mom1", "mom3", "mom5", "mom10", "mom20", "mom60", "ma20_slope", "dist_ma20", "volatility10", "atr14_pct", "close_position", "amount20", "market20", "market1", "relative20", "next_gap"]
forward = [f"{p}{h}" for h in [1,3,5,10,20] for p in ["fwd", "market_fwd"]]
events = pool.merge(daily[["ts_code", "trade_date", *features, *forward]], on=["ts_code", "trade_date"], how="left", validate="one_to_one").merge(pred,on=["ts_code", "trade_date"],how="left",validate="one_to_one")
events = events.merge(sectors,on=["trade_date","industry"],how="left",validate="many_to_one")
financial_matches=[]
for date in sorted(events.trade_date.unique()):
    available=financials[financials.announcement_date.le(date)].sort_values(["report_date","announcement_date"]).drop_duplicates("ts_code",keep="last")
    matched=events.loc[events.trade_date.eq(date),["ts_code","trade_date"]].merge(available,on="ts_code",how="left")
    financial_matches.append(matched)
events=events.merge(pd.concat(financial_matches),on=["ts_code","trade_date"],how="left",validate="one_to_one")
events["industry_count"] = events.groupby(["trade_date", "industry"]).ts_code.transform("count")
events["largest"] = events.industry_count.eq(events.groupby("trade_date").industry_count.transform("max"))
events["dist_ma60"] = events.close/events.ma60-1
events["trend_gap"] = events.trend_short/events.bull_bear-1
events["dist_bull_bear"] = events.close/events.bull_bear-1
events["prob_percentile"] = events.groupby("trade_date").prob_up.rank(pct=True)
events["industry_mom5"] = events.groupby(["trade_date", "industry"]).mom5.transform("mean")
events["industry_mom20"] = events.groupby(["trade_date", "industry"]).mom20.transform("mean")
events["month"] = events.trade_date.str[:6]
for h in [1,3,5,10,20]:
    events[f"excess{h}"] = events[f"fwd{h}"]-events[f"market_fwd{h}"]


def stats(f):
    result = {"events":len(f), "stocks":f.ts_code.nunique(), "dates":f.trade_date.nunique()}
    for h in [1,3,5,10,20]:
        v=f.dropna(subset=[f"fwd{h}"])
        result[f"h{h}"]={"n":len(v),"gross_pct":v[f"fwd{h}"].mean()*100,
            "net_pct":(v[f"fwd{h}"].mean()-.002)*100,"win_pct":v[f"fwd{h}"].gt(0).mean()*100,
            "excess_pct":v[f"excess{h}"].mean()*100,
            "day_equal_excess_pct":v.groupby("trade_date")[f"excess{h}"].mean().mean()*100}
    return result


ranked = events[events.prob_up.notna()].sort_values(["trade_date", "prediction_rank"])
top = ranked.groupby("trade_date", sort=False).head(3)
largest = ranked[ranked.largest]
largest_top = largest.groupby("trade_date", sort=False).head(3)
report = {"period":[START,ASOF],"pool":stats(events),"stages":{k:stats(f) for k,f in {
    "B1_all":events, "B1_predicted":ranked, "B1_prediction_top3":top,
    "largest_industry_all":events[events.largest], "largest_industry_predicted":largest,
    "largest_industry_top3":largest_top}.items()}}
quality=pool.merge(daily[["ts_code","trade_date","close"]],on=["ts_code","trade_date"],suffixes=("_csv","_db"),how="left")
recent=daily[daily.trade_date.ge(START)]
price_error=((recent.close/recent.pre_close-1)*100-recent.pct_chg).abs()
report["data_quality"]={"daily_rows":len(recent),"csv_missing_prices":quality.close_db.isna().sum(),
    "csv_close_diff_gt_001":(quality.close_csv-quality.close_db).abs().gt(.011).sum(),
    "pctchg_diff_gt_005pp":price_error.gt(.05).sum(),"max_pctchg_diff_pp":price_error.max(),
    "ohlc_inconsistent":((recent.high+1e-8<recent[["open","close"]].max(axis=1))|(recent.low-1e-8>recent[["open","close"]].min(axis=1))).sum(),
    "duplicate_price_rows":recent.duplicated(["ts_code","trade_date"]).sum(),
    "rounded_b1_boundary_rows":((pool.vol_ratio==1)|(pool.j==15)|(pool.close==pool.ma60)|(pool.trend_short==pool.bull_bear)|(pool.close==pool.bull_bear)).sum(),
    "strict_b1_rule_violations":((pool.vol_ratio>1)|(pool.j>15)|(pool.close<pool.ma60)|(pool.trend_short<pool.bull_bear)|(pool.close<pool.bull_bear)).sum(),
    "b1_mom5_negative_pct":events.mom5.lt(0).mean()*100,
    "median_mom5_pct":events.mom5.median()*100,"median_mom20_pct":events.mom20.median()*100,
    "sector_coverage_pct":events.sector_score.notna().mean()*100,
    "financial_roe_coverage_pct":events.roe.notna().mean()*100,
    "largest_sector_top10_fraction_pct":events.loc[events.largest,"sector_rank"].le(10).mean()*100,
    "largest_sector_rank_median":events.loc[events.largest,"sector_rank"].median()}
print("Analysing factors and prediction calibration", flush=True)
valid=ranked.dropna(subset=["fwd1"])
y=valid.fwd1.gt(0).astype(float)
prediction=valid.prob_up
n1=y.sum(); n0=len(y)-n1
auc=(prediction.rank()[y.eq(1)].sum()-n1*(n1+1)/2)/(n1*n0)
report["prediction"]={"n":len(valid),"prob_mean":prediction.mean(),"prob_min":prediction.min(),"prob_max":prediction.max(),"actual_up":y.mean(),"auc":auc,
    "brier":((prediction-y)**2).mean(),"constant_brier":((y-y.mean())**2).mean(),
    "by_probability":{label:stats(ranked[(ranked.prob_up>=lo)&(ranked.prob_up<hi)]) for label,lo,hi in [("below_50",0,.5),("50_to_55",.5,.55),("55_to_60",.55,.6),("60_plus",.6,1.01)]}}
aucs=[]
ics={1:[],5:[],20:[]}
for date,f in ranked.groupby("trade_date"):
    f=f.dropna(subset=["fwd1"])
    target=f.fwd1.gt(0)
    positives=target.sum(); negatives=len(target)-positives
    if positives and negatives:
        aucs.append((f.prob_up.rank()[target].sum()-positives*(positives+1)/2)/(positives*negatives))
    for h in ics:
        v=f.dropna(subset=[f"fwd{h}"])
        if len(v)>3 and v.prob_up.nunique()>1 and v[f"fwd{h}"].nunique()>1:
            ics[h].append(v.prob_up.rank().corr(v[f"fwd{h}"].rank()))
report["prediction"]["daily_auc_mean"]=np.mean(aucs)
report["prediction"]["daily_auc_dates"]=len(aucs)
report["prediction"]["daily_rank_ic_mean"]={h:np.mean(values) for h,values in ics.items()}
report["prediction"]["daily_auc_minus_05_ci"]=np.asarray(block_ci(np.asarray(aucs)-.5))/100
report["monthly"]={month:{"B1":stats(f),"top3":stats(top[top.month.eq(month)]),"largest_top3":stats(largest_top[largest_top.month.eq(month)])} for month,f in events.groupby("month")}
factor_names=["prob_up","j","vol_ratio","mom5","mom20","relative20","dist_ma60","dist_bull_bear","trend_gap","ma20_slope","volatility10","atr14_pct","close_position","amount20","industry_count","industry_mom5","industry_mom20","days_since","sector_score","sector_return5","sector_breadth","sector_relative","roe","debt_to_assets","ocf_per_share"]
factor_report={}
split=sorted(events.trade_date.unique())[len(events.trade_date.unique())//2]
for factor in factor_names:
    f=events.dropna(subset=[factor,"fwd5"]).copy()
    percentiles=f.groupby("trade_date")[factor].rank(pct=True)
    f["bucket"]=np.select([percentiles<=1/3,percentiles<=2/3],["low","mid"],default="high")
    per=f.groupby(["trade_date","bucket"]).excess5.mean().unstack().reindex(columns=["low","mid","high"])
    spread=(per.high-per.low).dropna()
    factor_report[factor]={"buckets":{b:{"n":len(v),"factor_median":v[factor].median(),"fwd5_net_pct":(v.fwd5.mean()-.002)*100,"excess5_pct":v.excess5.mean()*100,"fwd20_net_pct":(v.fwd20.mean()-.002)*100} for b,v in f.groupby("bucket")},
        "high_minus_low_5d_pp":spread.mean()*100,"block95ci_pp":block_ci(spread.values),
        "early_spread_pp":spread[spread.index<split].mean()*100,"late_spread_pp":spread[spread.index>=split].mean()*100}
report["factor_terciles"]=factor_report
report["split_date"]=split
# Partial associations after simultaneous controls, not independent causal effects.
reg_cols=["prob_up","j","vol_ratio","mom5","mom20","dist_ma60","volatility10","amount20","industry_count","close_position"]
reg=events.dropna(subset=[*reg_cols,"fwd5"]).copy()
X=reg[reg_cols].copy()
X["amount20"]=np.log1p(X.amount20)
for col in reg_cols:
    X[col]=X[col]-X[col].groupby(reg.trade_date).transform("mean")
X=X/X.std()
Y=reg.fwd5-reg.groupby("trade_date").fwd5.transform("mean")
def ols(mask):
    return dict(zip(reg_cols,np.linalg.lstsq(X.loc[mask].to_numpy(),Y.loc[mask].to_numpy(),rcond=None)[0]*100))
report["partial_5d_pct_per_sd"]={"all":ols(pd.Series(True,index=reg.index)),"early":ols(reg.trade_date<split),"late":ols(reg.trade_date>=split)}
report["market_regimes"]={name:stats(f) for name,f in {
    "market20_positive":events[events.market20>0],"market20_nonpositive":events[events.market20<=0],
    "stock5_positive":events[events.mom5>0],"stock5_nonpositive":events[events.mom5<=0],
    "industry5_positive":events[events.industry_mom5>0],"industry5_nonpositive":events[events.industry_mom5<=0]}.items()}
report["industry_leaders"] = events[events.largest].groupby("industry").agg(dates=("trade_date","nunique"),events=("ts_code","size"),mean_mom5=("mom5","mean"),mean_fwd5=("fwd5","mean")).sort_values("dates",ascending=False).head(12).reset_index().to_dict("records")

print("Replaying portfolio ablations and trade paths", flush=True)
sim_bars=daily[daily.trade_date.ge(START)&daily.ts_code.isin(events.ts_code)].copy()
by_date=zb1._bars_by_date(sim_bars)
sim_dates=[d for d in dates if d>=START]
def ranks_for(frame, sort_col="prediction_rank", ascending=True):
    f=frame.sort_values(["trade_date",sort_col,"ts_code"],ascending=[True,ascending,True]).copy()
    f["prediction_rank"]=f.groupby("trade_date").cumcount()+1
    return {str(d):v.fillna("").to_dict("records") for d,v in f.groupby("trade_date",sort=True)}
def sim_summary(result):
    t=pd.DataFrame(result["trades"])
    c=pd.DataFrame(result["curve"])
    return {"total_pct":(c.iloc[-1].nav-1)*100,"drawdown_pct":c.drawdown_pct.min(),"trades":len(t),
        "net_mean_pct":t.net_return_pct.mean() if len(t) else None,"win_pct":t.net_return_pct.gt(0).mean()*100 if len(t) else None,
        "avg_holdings":c.iloc[1:].position_count.mean()}
variants={"production":zb1.load_rankings(ROOT/"data",ASOF),"no_industry_filter":ranks_for(ranked),
    "reverse_prediction_largest":ranks_for(largest,"prob_up",False),
    "largest_low_volatility":ranks_for(largest,"volatility10"),
    "largest_momentum5_desc":ranks_for(largest,"mom5",False),
    "B1_low_volatility":ranks_for(events.dropna(subset=["volatility10"]),"volatility10"),
    "largest_positive_momentum":ranks_for(largest[largest.mom5>0]),
    "largest_market20_positive":ranks_for(largest[largest.market20>0]),
    "largest_sector_top10":ranks_for(largest[largest.sector_rank<=10]),
    "largest_sector_return5_positive":ranks_for(largest[largest.sector_return5>0])}
# Correct reverse score ordering: low predicted probability first.
variants["reverse_prediction_largest"]=ranks_for(largest,"prob_up",True)
results={}
with patch.object(zb1,"_bars_by_date",return_value=by_date):
    for name,ranks in variants.items():
        results[name]=zb1.simulate(sim_bars,ranks,sim_dates)
    report["ablation_portfolios"]={k:sim_summary(v) for k,v in results.items()}
    random_out=[]
    for _ in range(150):
        rr=largest.copy()
        rr["random"]=RNG.random(len(rr))
        random_out.append(sim_summary(zb1.simulate(sim_bars,ranks_for(rr,"random"),sim_dates))["total_pct"])
    prod=report["ablation_portfolios"]["production"]["total_pct"]
    report["largest_random_150"]={"mean":np.mean(random_out),"median":np.median(random_out),"p05":np.quantile(random_out,.05),"p95":np.quantile(random_out,.95),"production_percentile":np.mean(np.array(random_out)<=prod)*100}
production=results["production"]
saved=next(s for s in json.loads((ROOT/"web/data/strategies.json").read_text())["strategies"] if s["id"]=="zb1")
assert production==saved["portfolio"], "Production replay must match saved portfolio"
trade_frame=pd.DataFrame(production["trades"]).rename(columns={"signal_date":"trade_date"}).merge(events,on=["ts_code","trade_date"],suffixes=("","_event"))
report["actual_trades"]={"by_outcome":{k:{"n":len(f),"mean_net_pct":f.net_return_pct.mean(),"mean_probability":f.prob_up.mean(),"median_volatility10_pct":f.volatility10.median()*100,"median_mom5_pct":f.mom5.median()*100,"median_j":f.j.median(),"median_atr14_pct":f.atr14_pct.median()*100} for k,f in trade_frame.groupby("outcome")},
    "industry":trade_frame.groupby("industry").agg(trades=("ts_code","size"),mean_net_pct=("net_return_pct","mean")).sort_values("trades",ascending=False).reset_index().to_dict("records")}
losses=trade_frame[trade_frame.outcome.eq("loss")]
winmean=trade_frame[trade_frame.outcome.eq("win")].net_return_pct.mean()
lossmean=-losses.net_return_pct.mean()
report["actual_trades"]["break_even_win_pct"]=lossmean/(winmean+lossmean)*100
report["actual_trades"]["stop_loss_worse_than_55_pct_count"]=losses.net_return_pct.lt(-5.5).sum()
report["actual_trades"]["worst_net_pct"]=trade_frame.net_return_pct.min()
report["actual_trades"]["median_stop_in_atr_units"]=.05/trade_frame.atr14_pct.median()
report["actual_trades"]["monthly"]=trade_frame.groupby("month").agg(trades=("ts_code","size"),mean_net_pct=("net_return_pct","mean")).reset_index().to_dict("records")
# Independent complete-20-session events, using the identical OHLC/T+1 exits.
paths=[]
for row in events[events.fwd20.notna()].to_dict("records"):
    date=row["trade_date"]; code=row["ts_code"]; ix=di[date]
    window=[by_date.get(dates[ix+i],{}).get(code) for i in range(1,21)]
    if any(b is None for b in window):
        continue
    entry=window[0]["adj_open"]
    position={"entry_adjusted":entry,"profit_armed":False}
    fill=None; exit_day=None
    armed_day=None
    for offset,b in enumerate(window,1):
        fill=zb1.exit_fill(position,b,can_sell=offset>1)
        if position["profit_armed"] and armed_day is None: armed_day=offset
        if fill: exit_day=offset; break
    peak=max(b["adj_high"]/entry-1 for b in window)
    stopped=bool(fill and "止损" in fill[1])
    paths.append({"trade_date":date,"ts_code":code,"largest":row["largest"],"prob_up":row["prob_up"],
        "peak20":peak,"fwd20":row["fwd20"],"stop":stopped,"exit":fill is not None,
        "profit_exit":bool(fill and not stopped),"armed_before_exit":position["profit_armed"],
        "stop_then_end_positive":stopped and row["fwd20"]>0,
        "stop_and_window_hit15":stopped and peak>.15,"exit_day":exit_day,
        "return":fill[0]/entry-1 if fill else row["fwd20"]})
pathdf=pd.DataFrame(paths)
def pathstats(f):
    return {"n":len(f),"touch15_20d_pct":f.peak20.gt(.15).mean()*100,
        "stop_before_profit_pct":f.stop.mean()*100,"profit_exit_pct":f.profit_exit.mean()*100,
        "not_exited_pct":(~f.exit).mean()*100,"stop_later_positive_fraction_pct":f.loc[f.stop,"stop_then_end_positive"].mean()*100,
        "stop_and_window_hit15_fraction_pct":f.loc[f.stop,"stop_and_window_hit15"].mean()*100,
        "end20_gross_pct":f.fwd20.mean()*100,"exit_or_mark20_gross_pct":f['return'].mean()*100}
report["complete20_paths"]={"all_B1":pathstats(pathdf),"largest":pathstats(pathdf[pathdf.largest])}
report["path_probability_terciles"]={}
pathvalid=pathdf[pathdf.prob_up.notna()].copy()
pathvalid["q"]=pd.cut(pathvalid.groupby("trade_date").prob_up.rank(pct=True),[0,1/3,2/3,1],labels=["low","mid","high"])
for q,v in pathvalid.groupby("q",observed=True):report["path_probability_terciles"][str(q)]=pathstats(v)
# Stable, interpretable buckets for repeated hits and golden-pit confirmation.
report["confirmation_factors"]={k:stats(f) for k,f in {
    "repeat_next_day":events[events.days_since.eq(1)],"repeat_2_to_5":events[events.days_since.between(2,5)],
    "new_or_gap_gt5":events[events.days_since.isna()|events.days_since.gt(5)],
    "golden_pit_today":events[events.gp_signal.eq(1)],"no_golden_pit_today":events[~events.gp_signal.eq(1)],
    "next_gap_up_gt2pct":events[events.next_gap>.02],"next_gap_between_minus2_plus2":events[events.next_gap.between(-.02,.02)],
    "next_gap_down_gt2pct":events[events.next_gap<-.02]}.items()}
output=ROOT/"reports/zb1_diagnosis_20260904.json"
output.write_text(json.dumps(clean(report),ensure_ascii=False,indent=2,allow_nan=False))
print(str(output),flush=True)
print(json.dumps(clean({k:report[k] for k in ["data_quality","prediction","ablation_portfolios","actual_trades"]}),ensure_ascii=False,indent=2),flush=True)
