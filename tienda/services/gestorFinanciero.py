from decimal import Decimal
from tienda.models import ConfiguracionFiscal, ViniloMusical

class GestorFinanciero:
    
    @staticmethod
    def calcularTotalesCarrito(carritoDict, codigoCuponObj=None):
        """
        Recibe el diccionario de sesión del carrito y retorna totales.
        carritoDict = {'id_producto': cantidad, ...}
        """
        subtotal = Decimal('0.00')
        itemsDetalle = []
        
        # 1. Calcular Subtotal (Usando precio con descuento individual si existe)
        for productoId, cantidad in carritoDict.items():
            try:
                producto = ViniloMusical.objects.get(pk=productoId)
                
                # PRECIO REAL (Si tiene oferta del 20%, usa ese precio)
                precioReal = Decimal(producto.obtenerPrecioFinal())
                
                totalLinea = precioReal * int(cantidad)
                subtotal += totalLinea
                
                itemsDetalle.append({
                    'producto': producto,
                    'cantidad': cantidad,
                    'total': totalLinea,
                    # Guardamos esto para saber qué precio se cobró
                    'precio_aplicado': precioReal 
                })
            except ViniloMusical.DoesNotExist:
                continue

        # 2. Calcular Descuento Global (Cupón al final de la compra)
        montoDescuento = Decimal('0.00')
        if codigoCuponObj and codigoCuponObj.activo:
            montoDescuento = subtotal * codigoCuponObj.porcentajeDescuento

        subtotalConDescuento = subtotal - montoDescuento

        # 3. Calcular IVA
        tasaIva = ConfiguracionFiscal.obtenerIvaActual()
        # Convertimos a Decimal por seguridad
        tasaIva = Decimal(str(tasaIva)) 
        
        montoImpuesto = subtotalConDescuento * tasaIva
        totalPagar = subtotalConDescuento + montoImpuesto
        
        return {
            'items': itemsDetalle,
            'subtotal': subtotal,
            'descuento': montoDescuento,
            'impuesto': montoImpuesto,
            'total': totalPagar,
            'iva_porcentaje': int(tasaIva * 100)
        }
