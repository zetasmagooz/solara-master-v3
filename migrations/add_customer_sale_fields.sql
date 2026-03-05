-- Migration: Add customer fields + sale customer/tax_type columns
-- Run against: solara_dev (local) and solara_stg (VPS)

-- Customer extensions
ALTER TABLE customers ADD COLUMN IF NOT EXISTS last_name VARCHAR(200);
ALTER TABLE customers ADD COLUMN IF NOT EXISTS gender VARCHAR(20);
ALTER TABLE customers ADD COLUMN IF NOT EXISTS birth_date DATE;
ALTER TABLE customers ADD COLUMN IF NOT EXISTS image_url TEXT;

-- Sale extensions
ALTER TABLE sales ADD COLUMN IF NOT EXISTS customer_id UUID REFERENCES customers(id);
ALTER TABLE sales ADD COLUMN IF NOT EXISTS tax_type VARCHAR(20);
