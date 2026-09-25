"""Resolving which active Offer applies to a product.

Product.final_price asks for its best offer; list views call
attach_offers() once so a page of N products costs one offer query,
not N.
"""
from .models import Offer


def active_offers(now=None):
    offers = list(Offer.objects.active(now).prefetch_related('products', 'categories'))
    for offer in offers:
        offer._product_ids = {p.pk for p in offer.products.all()}
        offer._category_ids = {c.pk for c in offer.categories.all()}
    return offers


def best_offer_for(product, offers):
    """The applicable offer giving the lowest price (ties: newest offer)."""
    best, best_price = None, product.price
    for offer in offers:
        if product.pk in offer._product_ids or product.category_id in offer._category_ids:
            price = offer.price_for(product.price)
            if price < best_price:
                best, best_price = offer, price
    return best


def attach_offers(products, offers=None):
    offers = active_offers() if offers is None else offers
    for product in products:
        product._active_offer = best_offer_for(product, offers)
    return products
