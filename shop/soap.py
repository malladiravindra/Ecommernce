from django.contrib.auth.models import User
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.encoding import smart_bytes
from xml.etree import ElementTree as ET

from .models import Product, Cart, CartItem

SOAP_NS = 'http://schemas.xmlsoap.org/soap/envelope/'
XML_NS = 'http://www.w3.org/2001/XMLSchema'
ET.register_namespace('soapenv', SOAP_NS)


def _build_response(body_element):
    envelope = ET.Element(ET.QName(SOAP_NS, 'Envelope'))
    body = ET.SubElement(envelope, ET.QName(SOAP_NS, 'Body'))
    body.append(body_element)
    xml = ET.tostring(envelope, encoding='utf-8', xml_declaration=True)
    return HttpResponse(xml, content_type='text/xml')


def _build_fault(message):
    fault = ET.Element(ET.QName(SOAP_NS, 'Fault'))
    faultcode = ET.SubElement(fault, 'faulted')
    faultcode.text = 'Server'
    faultstring = ET.SubElement(fault, 'faultstring')
    faultstring.text = message
    return _build_response(fault)


def _get_action_name(body):
    for child in body:
        return child.tag.split('}')[-1]
    return None


def _parse_int(element, default=0):
    if element is None or element.text is None:
        return default
    try:
        return int(element.text.strip())
    except (ValueError, TypeError):
        return default


@csrf_exempt
def soap_application(request):
    if request.method == 'GET':
        html = '<html><body><h1>SOAP endpoint</h1><p>Send POST XML to this URL.</p></body></html>'
        return HttpResponse(html, content_type='text/html')

    if request.method != 'POST':
        return HttpResponse(status=405)

    try:
        root = ET.fromstring(request.body or b'')
    except ET.ParseError as exc:
        return _build_fault(f'Invalid XML: {exc}')

    body = root.find(f'.//{{{SOAP_NS}}}Body')
    if body is None or len(body) == 0:
        return _build_fault('SOAP Body is missing')

    action_element = body[0]
    action = _get_action_name(body)
    if action == 'listProducts':
        response = ET.Element('listProductsResponse')
        products_el = ET.SubElement(response, 'products')
        for product in Product.objects.filter(is_active=True):
            product_el = ET.SubElement(products_el, 'product')
            for field_name, value in [
                ('id', product.id),
                ('name', product.name),
                ('slug', product.slug),
                ('description', product.description or ''),
                ('price', float(product.price)),
                ('discount_price', float(product.discount_price or 0.0)),
                ('final_price', float(product.final_price)),
                ('stock', product.stock),
                ('is_active', str(product.is_active).lower()),
                ('featured', str(product.featured).lower()),
            ]:
                field_el = ET.SubElement(product_el, field_name)
                field_el.text = str(value)
        return _build_response(response)

    if action == 'getProduct':
        product_id = _parse_int(action_element.findtext('product_id'))
        product = Product.objects.filter(id=product_id, is_active=True).first()
        if not product:
            return _build_fault(f'Product with id={product_id} not found')
        response = ET.Element('getProductResponse')
        for field_name, value in [
            ('id', product.id),
            ('name', product.name),
            ('slug', product.slug),
            ('description', product.description or ''),
            ('price', float(product.price)),
            ('discount_price', float(product.discount_price or 0.0)),
            ('final_price', float(product.final_price)),
            ('stock', product.stock),
            ('is_active', str(product.is_active).lower()),
            ('featured', str(product.featured).lower()),
        ]:
            field_el = ET.SubElement(response, field_name)
            field_el.text = str(value)
        return _build_response(response)

    if action == 'addToCart':
        user_id = _parse_int(action_element.findtext('user_id'))
        product_id = _parse_int(action_element.findtext('product_id'))
        quantity = _parse_int(action_element.findtext('quantity'), default=1)

        user = User.objects.filter(id=user_id).first()
        if not user:
            return _build_fault(f'User with id={user_id} not found')

        product = Product.objects.filter(id=product_id, is_active=True).first()
        if not product:
            return _build_fault(f'Product with id={product_id} not found')

        if quantity < 1:
            return _build_fault('Quantity must be at least 1')

        if product.stock < quantity:
            return _build_fault(f'Only {product.stock} items available in stock.')

        cart, _ = Cart.objects.get_or_create(user=user)
        cart_item, created = CartItem.objects.get_or_create(cart=cart, product=product)
        if not created:
            cart_item.quantity += quantity
        else:
            cart_item.quantity = quantity
        cart_item.save()

        response = ET.Element('addToCartResponse')
        ET.SubElement(response, 'message').text = f'Added {quantity} of {product.name} to cart.'
        ET.SubElement(response, 'cart_count').text = str(sum(item.quantity for item in cart.items.all()))
        return _build_response(response)

    return _build_fault(f'Unsupported SOAP action: {action}')
