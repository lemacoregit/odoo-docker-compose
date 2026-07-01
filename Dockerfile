FROM mraldirs1231/lemaerp19e:19.0.2

USER root

COPY ./etc/requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

USER odoo