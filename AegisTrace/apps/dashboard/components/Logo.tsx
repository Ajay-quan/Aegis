// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
// The Aegis wordmark: the word itself, set in the house face. Product names extend it
// ("Aegis" quiet, the product bright), so every product reads as part of one family.
import Link from "next/link";

export function Logo({ href = "/welcome", product, size = 17 }: { href?: string; product?: string; size?: number }) {
  return (
    <Link href={href} className="aegis-logo" style={{ fontSize: size }} aria-label={product ? `Aegis ${product}` : "Aegis"}>
      <span className="aegis-logo-word">Aegis</span>
      {product ? <span className="aegis-logo-product">{product}</span> : null}
    </Link>
  );
}

/** A product name in the logo's type: AegisMem, AegisTrace, ... */
export function ProductName({ name }: { name: string }) {
  return (
    <span className="aegis-product">
      <span className="aegis-product-prefix">Aegis</span>{name}
    </span>
  );
}
