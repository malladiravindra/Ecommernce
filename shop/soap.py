"""Public, read-only SOAP catalogue endpoint (listProducts / getProduct).

It exposes the same public data as GET /api/products/ and performs no
writes and no per-user actions, so it is exempt from CSRF (SOAP clients
have no browser session or token). Incoming XML is parsed with defusedxml.
"""
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from xml.etree import ElementTree as ET

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

from .models import Product

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
        root = SafeET.fromstring(request.body or b'')
    except (ET.ParseError, DefusedXmlException):
        return _build_fault('Invalid or unsafe XML')

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

    return _build_fault(f'Unsupported SOAP action: {action}')
