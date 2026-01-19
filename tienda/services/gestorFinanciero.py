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
        
        # 1. Calcular Subtotal Bruto
        for productoId, cantidad in carritoDict.items():
            try:
                producto = ViniloMusical.objects.get(pk=productoId)
                totalLinea = producto.precioUnitario * int(cantidad)
                subtotal += totalLinea
                itemsDetalle.append({
                    'producto': producto,
                    'cantidad': cantidad,
                    'total': totalLinea
                })
            except ViniloMusical.DoesNotExist:
                continue

        # 2. Calcular Descuento
        montoDescuento = Decimal('0.00')
        if codigoCuponObj and codigoCuponObj.activo:
            montoDescuento = subtotal * codigoCuponObj.porcentajeDescuento

        subtotalConDescuento = subtotal - montoDescuento

        # 3. Calcular IVA (Dinámico desde DB)
        tasaIva = ConfiguracionFiscal.obtenerIvaActual()
        montoImpuesto = subtotalConDescuento * tasaIva
        
        totalPagar = subtotalConDescuento + montoImpuesto
        
        return {
            'items': itemsDetalle,
            'subtotal': subtotal,
            'descuento': montoDescuento,
            'impuesto': montoImpuesto,
            'total': totalPagar
        }
