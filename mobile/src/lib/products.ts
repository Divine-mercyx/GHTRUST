const PRODUCT_NAME: Record<string, string> = {
  business_loan: 'Business loan',
  payday_loan: 'Payday loan',
  study_loan: 'Study loan',
  asset_loan: 'Asset loan',
  lpo_invoice_financing: 'LPO / invoice financing',
  cluster_group_loan: 'Group loan',
};

/** "8% monthly", or "7% one-off charge" for products charged once for the whole loan (LPO). */
export const rateLabel = (rate: string | number, method?: string | null) =>
  method === 'one_off' ? `${Number(rate)}% one-off charge` : `${Number(rate)}% monthly`;

/** Built-in names, else a readable version of the code ("agric_loan" → "Agric loan")
 * for products staff create in the admin portal. */
export const productName = (code: string) => {
  if (PRODUCT_NAME[code]) return PRODUCT_NAME[code];
  const words = code.replace(/_/g, ' ').trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
};
