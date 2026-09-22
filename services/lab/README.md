# آزمایشگاه استراتژی

سه قانون:
۱. داده‌های بعد از ۲۰۲۵-۱۲-۲۲ قفل است (holdout). توسعه فقط روی قبل از آن انجام می‌شود.
۲. هر اجرا در `data/lab/trials.jsonl` ثبت می‌شود و Deflated Sharpe تعداد کل آزمایش‌ها را حساب می‌کند.
۳. هر استراتژی فقط **یک بار** روی holdout اجرا می‌شود. تغییر پارامتر = استراتژی جدید با نام جدید.

```bash
uv run python -m services.lab.cli fetch        # دانلود ۱۰ دارایی (چند دقیقه)
uv run python -m services.lab.cli list
uv run python -m services.lab.cli run all      # همه روی دورهٔ توسعه
uv run python -m services.lab.cli trials
uv run python -m services.lab.cli holdout NAME # فقط اگر هر سه تیک توسعه ✅ بود
```

معیار عبور (از قبل در کد ثابت شده):
- توسعه: Deflated Sharpe ≥ ۹۵٪، هر دو نیمه سودده، افت سرمایه کمتر از خرید و نگهداری.
- holdout: سودده، PF ≥ ۱.۱، افت کمتر از خرید و نگهداری، PSR ≥ ۹۰٪.

holdout برای `trend-2r` تمیز نیست، چون قبلاً روی کل داده تست شده بود.
